"""Free inference transport, bounded work and privacy contracts."""

import asyncio
import base64
import copy
import json
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from types import SimpleNamespace

import httpx
import pytest
import structlog
from pydantic import SecretStr

from app.exceptions.domain_exceptions import (
    LlmClientError,
    LlmQuotaExhaustedError,
    LlmUnavailableError,
)
from app.services.llm.openrouter_llm_client import OpenRouterLlmClient
from app.services.llm.retry_policy import retry_after_seconds
from app.services.llm.structured_schema import structured_schema


@pytest.fixture
def configured_settings():
    return SimpleNamespace(
        openrouter_api_key=SecretStr("test-key"),
        openrouter_receipt_models=["synthetic/model:free"],
        openrouter_recipe_models=["synthetic/model:free"],
        openrouter_allowed_providers=["synthetic-host"],
        openrouter_max_attempts=2,
        openrouter_request_timeout_seconds=25,
        openrouter_completion_timeout_seconds=40,
        openrouter_retry_backoff_max_seconds=0,
        openrouter_max_output_tokens=8192,
    )


def completion(content='{"lines": []}', **message):
    return {
        "choices": [
            {"finish_reason": "stop", "message": {"content": content, **message}}
        ]
    }


def make_client(settings, handler):
    return OpenRouterLlmClient(
        settings=settings, transport=httpx.MockTransport(handler)
    )


async def test_image_schema_and_routing_are_explicit(configured_settings):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=completion())

    client = make_client(configured_settings, handler)
    try:
        assert await client.complete(
            prompt="synthetic",
            response_schema={"type": "object"},
            image=b"synthetic-image",
            image_content_type="image/png",
        ) == {"lines": []}
        payload = json.loads(calls[0].content)
        assert calls[0].url == "https://openrouter.ai/api/v1/chat/completions"
        assert calls[0].headers["Authorization"] == "Bearer test-key"
        assert payload["provider"] == {
            "only": ["synthetic-host"],
            "allow_fallbacks": False,
            "require_parameters": True,
            "data_collection": "deny",
            "max_price": {"prompt": 0, "completion": 0, "request": 0, "image": 0},
        }
        assert payload["stream"] is False
        assert payload["max_tokens"] == 8192
        assert payload["response_format"]["json_schema"] == {
            "name": "structured_completion",
            "strict": True,
            "schema": {"type": "object", "required": [], "additionalProperties": False},
        }
        image = payload["messages"][0]["content"][1]["image_url"]["url"]
        assert (
            image
            == "data:image/png;base64," + base64.b64encode(b"synthetic-image").decode()
        )
    finally:
        await client.aclose()


@pytest.mark.parametrize("has_image", [False, True])
async def test_configured_models_are_used_without_catalogue_requests(
    configured_settings,
    has_image,
):
    configured_settings.openrouter_receipt_models = ["operator/receipt-model"]
    configured_settings.openrouter_recipe_models = ["operator/recipe-model"]
    requests = []

    def handler(request):
        requests.append(request)
        assert request.method == "POST"
        assert request.url.path == "/api/v1/chat/completions"
        return httpx.Response(200, json=completion())

    client = make_client(configured_settings, handler)
    try:
        await client.complete(
            prompt="synthetic",
            response_schema={},
            image=b"image" if has_image else None,
            image_content_type="image/png" if has_image else None,
        )
        assert len(requests) == 1
        payload = json.loads(requests[0].content)
        expected = "operator/receipt-model" if has_image else "operator/recipe-model"
        assert payload["model"] == expected
        assert all(price == 0 for price in payload["provider"]["max_price"].values())
    finally:
        await client.aclose()


@pytest.mark.parametrize("status,body", [(429, {}), (200, {"error": {"code": 429}})])
@pytest.mark.parametrize("retry,expected", [("12", 12), ("bad", None), (None, None)])
async def test_quota_stops_without_fallback(
    configured_settings, status, body, retry, expected
):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            status, json=body, headers={"Retry-After": retry} if retry else {}
        )

    client = make_client(configured_settings, handler)
    try:
        with pytest.raises(LlmQuotaExhaustedError) as caught:
            await client.complete(prompt="synthetic", response_schema={})
        assert caught.value.retry_after == expected
        assert len(calls) == 1
    finally:
        await client.aclose()


@pytest.mark.parametrize("status", [401, 402, 403])
@pytest.mark.parametrize("embedded", [False, True])
async def test_permanent_failure_does_not_retry(configured_settings, status, embedded):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            200 if embedded else status, json={"error": {"code": status}}
        )

    client = make_client(configured_settings, handler)
    try:
        with pytest.raises(LlmUnavailableError):
            await client.complete(prompt="synthetic", response_schema={})
        assert len(calls) == 1
    finally:
        await client.aclose()


@pytest.mark.parametrize("failure", ["transport", "html503", "404", "embedded503"])
async def test_shared_attempt_budget_and_configured_model_fallback(
    configured_settings, failure
):
    first = configured_settings.openrouter_recipe_models[0]
    second = "synthetic/second:free"
    configured_settings.openrouter_recipe_models.append(second)
    attempts = []

    def handler(request):
        attempts.append(json.loads(request.content))
        if len(attempts) == 1:
            if failure == "transport":
                raise httpx.ConnectError("private upstream body", request=request)
            if failure == "html503":
                return httpx.Response(503, text="private upstream body")
            if failure == "404":
                return httpx.Response(404, text="missing")
            return httpx.Response(200, json={"error": {"code": 503}})
        return httpx.Response(200, json=completion())

    client = OpenRouterLlmClient(
        settings=configured_settings, transport=httpx.MockTransport(handler)
    )
    try:
        await client.complete(prompt="synthetic", response_schema={})
        assert [p["model"] for p in attempts] == [first, second]
        assert all(p["provider"]["max_price"]["prompt"] == 0 for p in attempts)
    finally:
        await client.aclose()


async def test_transport_exhaustion_is_sanitized(configured_settings):
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ReadError("PRIVATE upstream", request=request)

    client = make_client(configured_settings, handler)
    try:
        with structlog.testing.capture_logs() as logs:
            with pytest.raises(LlmUnavailableError) as caught:
                await client.complete(prompt="PRIVATE prompt", response_schema={})
        assert len(calls) == 2
        assert caught.value.__cause__ is None
        assert caught.value.__suppress_context__
        assert "PRIVATE" not in str(logs) + str(caught.value)
        assert "test-key" not in str(logs)
    finally:
        await client.aclose()


@pytest.mark.parametrize(
    "body",
    [
        None,
        [],
        {},
        {"choices": []},
        {"choices": [None]},
        {"choices": [1]},
        completion(""),
        completion("private invalid JSON"),
        completion("[]"),
        completion('"string"'),
        completion("null"),
        completion("1"),
        completion(refusal="private refusal"),
        {"choices": [{"finish_reason": "length", "message": {"content": "{}"}}]},
        {"error": {"code": 400, "message": "private error"}},
        {"error": {"code": "Infinity", "message": "private error"}},
    ],
)
async def test_invalid_envelopes_do_not_retry_or_leak_content(
    configured_settings, body
):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=body)

    client = make_client(configured_settings, handler)
    try:
        with structlog.testing.capture_logs() as logs:
            with pytest.raises(LlmClientError) as caught:
                await client.complete(prompt="private prompt", response_schema={})
        assert not isinstance(caught.value, LlmUnavailableError)
        assert len(calls) == 1
        assert "private" not in str(logs) + str(caught.value)
        assert caught.value.__cause__ is None
    finally:
        await client.aclose()


@pytest.mark.parametrize("status", [400, 422])
async def test_bad_schema_request_never_loosens_or_retries(configured_settings, status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, json={"error": {"code": status}})

    client = make_client(configured_settings, handler)
    try:
        with pytest.raises(LlmClientError):
            await client.complete(prompt="synthetic", response_schema={})
        assert len(calls) == 1
    finally:
        await client.aclose()


@pytest.mark.parametrize(
    "field,value",
    [
        ("openrouter_api_key", None),
        ("openrouter_recipe_models", []),
        ("openrouter_allowed_providers", []),
    ],
)
async def test_missing_config_is_lazy_and_makes_no_network_calls(
    configured_settings, field, value
):
    setattr(configured_settings, field, value)

    def handler(request):
        pytest.fail("Missing config must not make HTTP requests")

    client = OpenRouterLlmClient(
        settings=configured_settings, transport=httpx.MockTransport(handler)
    )
    try:
        with pytest.raises(LlmUnavailableError):
            await client.complete(prompt="synthetic", response_schema={})
    finally:
        await client.aclose()


@pytest.mark.parametrize("stage", ["inference", "backoff"])
async def test_total_deadline_cancels_all_stages_without_more_attempts(
    configured_settings, stage, monkeypatch
):
    monkeypatch.setattr(
        "app.services.llm.openrouter_llm_client.random.uniform", lambda *_: 1
    )
    configured_settings.openrouter_completion_timeout_seconds = 0.02
    configured_settings.openrouter_retry_backoff_max_seconds = 1
    calls = []
    cancelled = asyncio.Event()

    async def handler(request):
        calls.append(request.url.path)
        if stage == "inference":
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        return httpx.Response(503)

    client = OpenRouterLlmClient(
        settings=configured_settings, transport=httpx.MockTransport(handler)
    )
    try:
        with pytest.raises(LlmUnavailableError):
            await asyncio.wait_for(
                client.complete(prompt="synthetic", response_schema={}), 1
            )
        assert calls.count("/api/v1/chat/completions") <= 1
        if stage != "backoff":
            assert cancelled.is_set()
    finally:
        await client.aclose()


async def test_external_cancellation_propagates(configured_settings):
    async def handler(request):
        raise asyncio.CancelledError

    client = OpenRouterLlmClient(
        settings=configured_settings, transport=httpx.MockTransport(handler)
    )
    try:
        with pytest.raises(asyncio.CancelledError):
            await client.complete(prompt="synthetic", response_schema={})
    finally:
        await client.aclose()


def test_schema_closes_nested_objects_preserves_refs_and_nullable_without_mutation():
    schema = {
        "type": "object",
        "title": "Receipt",
        "properties": {
            "line": {"$ref": "#/$defs/Line"},
            "optional": {"type": "number", "nullable": True, "default": None},
        },
        "$defs": {
            "Line": {"type": "object", "properties": {"text": {"type": "string"}}}
        },
    }
    original = copy.deepcopy(schema)
    normalized = structured_schema(schema)
    assert schema == original
    assert "title" not in normalized
    assert normalized["required"] == ["line", "optional"]
    assert normalized["additionalProperties"] is False
    assert normalized["properties"]["line"] == {"$ref": "#/$defs/Line"}
    assert normalized["properties"]["optional"] == {
        "anyOf": [{"type": "number"}, {"type": "null"}]
    }
    assert normalized["$defs"]["Line"]["additionalProperties"] is False


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, None),
        ("", None),
        ("12", 12),
        ("0", None),
        ("-1", None),
        ("1.5", None),
        ("604801", None),
        ("bad", None),
        ("∞", None),
    ],
)
def test_retry_after_validation(value, expected):
    assert retry_after_seconds(value) == expected


def test_retry_after_http_date_and_past():
    future = datetime.now(timezone.utc) + timedelta(seconds=30)
    assert 29 <= retry_after_seconds(format_datetime(future)) <= 30
    assert retry_after_seconds(format_datetime(future - timedelta(days=1))) is None


@pytest.mark.parametrize("code", [float("inf"), float("nan"), [], {}])
def test_malformed_embedded_error_code_is_a_controlled_failure(code):
    response = httpx.Response(200, text=json.dumps({"error": {"code": code}}))
    with pytest.raises(LlmClientError):
        OpenRouterLlmClient._read_response(response)


async def test_unsupported_image_type_never_reaches_inference(configured_settings):
    def handler(request):
        pytest.fail("Unsupported images must not reach inference")

    client = make_client(configured_settings, handler)
    try:
        with pytest.raises(LlmClientError):
            await client.complete(
                prompt="synthetic",
                response_schema={},
                image=b"x",
                image_content_type="image/gif",
            )
    finally:
        await client.aclose()


@pytest.mark.parametrize("status", [400, 422])
@pytest.mark.parametrize("embedded_code", [429, 503, 401])
async def test_http_schema_rejection_takes_precedence_over_embedded_code(
    configured_settings,
    status,
    embedded_code,
):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, json={"error": {"code": embedded_code}})

    client = make_client(configured_settings, handler)
    try:
        with pytest.raises(LlmClientError) as caught:
            await client.complete(prompt="synthetic", response_schema={})
        assert type(caught.value) is LlmClientError
        assert len(calls) == 1
    finally:
        await client.aclose()
