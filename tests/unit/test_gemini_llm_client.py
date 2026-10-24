import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from google.genai.errors import ClientError, ServerError
from structlog.testing import capture_logs

from app.config.settings import settings
from app.exceptions.domain_exceptions import LlmClientError
from app.services.llm.gemini_llm_client import GeminiLlmClient


@pytest.fixture(autouse=True)
def _fast_retries(monkeypatch):
    """Zero out the backoff so retry tests don't sleep for real, and pin the
    retry/fallback settings so a developer's .env cannot change the call count."""
    monkeypatch.setattr(settings, "gemini_retry_backoff_initial_seconds", 0)
    monkeypatch.setattr(settings, "gemini_retry_backoff_max_seconds", 0)
    monkeypatch.setattr(settings, "gemini_max_attempts", 3)
    monkeypatch.setattr(settings, "gemini_fallback_model", None)


def _client(side_effect) -> GeminiLlmClient:
    """A GeminiLlmClient whose SDK call is mocked, bypassing __init__.

    Mirrors FcmClient's test helper: real credentials are never needed
    because the underlying SDK client is replaced outright.
    """
    client = object.__new__(GeminiLlmClient)
    client._client = Mock()
    client._client.aio.models.generate_content = AsyncMock(side_effect=side_effect)
    return client


def _response(payload: dict) -> SimpleNamespace:
    return SimpleNamespace(text=json.dumps(payload))


def _server_error(code: int = 503) -> ServerError:
    return ServerError(code, {"message": "unavailable", "status": "UNAVAILABLE"})


def _client_error(code: int) -> ClientError:
    return ClientError(code, {"message": "bad request", "status": "INVALID_ARGUMENT"})


@pytest.mark.parametrize(
    "exc",
    [
        _server_error(500),
        _server_error(503),
        _client_error(408),
        _client_error(429),
        httpx.ConnectError("connection refused"),
        httpx.TimeoutException("timed out"),
    ],
)
def test_is_retryable_classifies_5xx_408_429_and_transport_errors_as_transient(exc):
    assert GeminiLlmClient._is_retryable(exc) is True


@pytest.mark.parametrize("code", [400, 401, 403, 404])
def test_is_retryable_classifies_other_4xx_as_permanent(code):
    assert GeminiLlmClient._is_retryable(_client_error(code)) is False


@pytest.mark.asyncio
async def test_retries_transient_error_then_succeeds():
    client = _client(
        side_effect=[_server_error(), _server_error(), _response({"ok": True})]
    )

    result = await client.complete(prompt="p", response_schema={})

    assert result == {"ok": True}
    assert client._client.aio.models.generate_content.await_count == 3


@pytest.mark.asyncio
async def test_retries_transport_error_then_succeeds():
    client = _client(
        side_effect=[
            httpx.ConnectError("connection refused"),
            httpx.TimeoutException("timed out"),
            _response({"ok": True}),
        ]
    )

    result = await client.complete(prompt="p", response_schema={})

    assert result == {"ok": True}
    assert client._client.aio.models.generate_content.await_count == 3


async def test_response_text_is_never_logged():
    client = _client(side_effect=[_response({"description": "SENTINEL-RECEIPT-TEXT"})])

    with capture_logs() as logs:
        await client.complete(prompt="p", response_schema={})

    assert "SENTINEL-RECEIPT-TEXT" not in str(logs)


@pytest.mark.asyncio
async def test_does_not_retry_permanent_client_error():
    client = _client(side_effect=[_client_error(400)])

    with pytest.raises(LlmClientError):
        await client.complete(prompt="p", response_schema={})

    assert client._client.aio.models.generate_content.await_count == 1


@pytest.mark.asyncio
async def test_exhausts_retries_and_raises_llm_client_error():
    client = _client(side_effect=[_server_error(), _server_error(), _server_error()])

    with pytest.raises(LlmClientError):
        await client.complete(prompt="p", response_schema={})

    assert client._client.aio.models.generate_content.await_count == 3


@pytest.mark.asyncio
async def test_falls_back_to_secondary_model_once_primary_is_exhausted(monkeypatch):
    monkeypatch.setattr(settings, "gemini_fallback_model", "fallback-model")
    monkeypatch.setattr(settings, "gemini_fallback_max_attempts", 2)
    client = _client(
        side_effect=[
            _server_error(),
            _server_error(),
            _server_error(),
            _response({"ok": True}),
        ]
    )

    result = await client.complete(prompt="p", response_schema={})

    assert result == {"ok": True}
    calls = client._client.aio.models.generate_content.await_args_list
    assert [call.kwargs["model"] for call in calls] == [
        settings.gemini_model,
        settings.gemini_model,
        settings.gemini_model,
        "fallback-model",
    ]


@pytest.mark.asyncio
async def test_no_fallback_configured_raises_once_primary_is_exhausted():
    assert settings.gemini_fallback_model is None
    client = _client(side_effect=[_server_error(), _server_error(), _server_error()])

    with pytest.raises(LlmClientError):
        await client.complete(prompt="p", response_schema={})

    assert client._client.aio.models.generate_content.await_count == 3


@pytest.mark.asyncio
async def test_permanent_error_on_primary_skips_the_fallback_model(monkeypatch):
    monkeypatch.setattr(settings, "gemini_fallback_model", "fallback-model")
    client = _client(side_effect=[_client_error(400)])

    with pytest.raises(LlmClientError):
        await client.complete(prompt="p", response_schema={})

    assert client._client.aio.models.generate_content.await_count == 1


@pytest.mark.asyncio
async def test_raises_once_both_primary_and_fallback_are_exhausted(monkeypatch):
    monkeypatch.setattr(settings, "gemini_fallback_model", "fallback-model")
    monkeypatch.setattr(settings, "gemini_fallback_max_attempts", 2)
    client = _client(side_effect=[_server_error()] * 5)

    with pytest.raises(LlmClientError):
        await client.complete(prompt="p", response_schema={})

    assert client._client.aio.models.generate_content.await_count == 5


@pytest.mark.parametrize("schema_name", ["CandidateBatch", "WritingBatch"])
async def test_recipe_schemas_work_through_google_sdk(schema_name):
    from google import genai
    from google.genai import types

    from app.schemas.recipes import recipe_schema

    requests = []
    payload = {"candidates": []} if schema_name == "CandidateBatch" else {"recipes": []}

    async def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "candidates": [{"content": {"parts": [{"text": json.dumps(payload)}]}}]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        sdk = genai.Client(
            api_key="test-key",
            http_options=types.HttpOptions(httpx_async_client=http),
        )
        client = object.__new__(GeminiLlmClient)
        client._client = sdk
        try:
            result = await client.complete(
                prompt="Generate recipes",
                response_schema=getattr(recipe_schema, schema_name).model_json_schema(),
            )
        finally:
            await sdk.aio.aclose()
            sdk.close()

    assert result == payload
    config = requests[0]["generationConfig"]
    assert config["responseMimeType"] == "application/json"
    root_field = "candidates" if schema_name == "CandidateBatch" else "recipes"
    assert "responseSchema" not in config
    assert root_field in config["responseJsonSchema"]["properties"]
    expected = getattr(recipe_schema, schema_name).model_json_schema()
    assert config["responseJsonSchema"] == expected
    assert "tools" not in requests[0]


async def test_generation_options_bound_output_and_use_low_thinking_for_gemini3(
    monkeypatch,
):
    monkeypatch.setattr(settings, "gemini_model", "gemini-3.6-flash")
    monkeypatch.setattr(settings, "gemini_max_output_tokens", 4096)
    monkeypatch.setattr(settings, "gemini_temperature", None)
    monkeypatch.setattr(settings, "gemini_seed", None)
    monkeypatch.setattr(settings, "gemini_thinking_level", "low")
    client = _client([_response({"ok": True})])
    await client.complete(prompt="p", response_schema={})
    config = client._client.aio.models.generate_content.await_args.kwargs["config"]
    assert config.max_output_tokens == 4096
    assert config.temperature is None
    assert config.thinking_config.thinking_level.value.upper() == "LOW"


async def test_generation_options_do_not_send_gemini3_thinking_to_older_models(
    monkeypatch,
):
    monkeypatch.setattr(settings, "gemini_model", "gemini-2.5-flash")
    monkeypatch.setattr(settings, "gemini_temperature", 0.2)
    monkeypatch.setattr(settings, "gemini_seed", 7)
    client = _client([_response({"ok": True})])
    await client.complete(prompt="p", response_schema={})
    config = client._client.aio.models.generate_content.await_args.kwargs["config"]
    assert config.thinking_config is None
    assert config.temperature == 0.2
    assert config.seed == 7


async def test_response_and_retry_logs_never_include_model_or_provider_text():
    import structlog

    secret = "private stock and cultural details"
    client = _client(
        [ServerError(503, {"message": secret}), _response({"secret": secret})]
    )
    with structlog.testing.capture_logs() as logs:
        result = await client.complete(prompt=secret, response_schema={})
    assert result["secret"] == secret
    assert secret not in json.dumps(logs)
    response_log = next(item for item in logs if item["event"] == "gemini_llm_response")
    assert response_log["response_chars"] > 0
    assert "raw_text" not in response_log


async def test_sdk_does_not_add_its_own_retry_budget(monkeypatch):
    from google import genai
    from google.genai import types

    requests = []

    async def respond(request):
        requests.append(request)
        if len(requests) < 3:
            return httpx.Response(
                503,
                json={
                    "error": {"code": 503, "message": "busy", "status": "UNAVAILABLE"}
                },
            )
        return httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": '{"ok":true}'}]}}]},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        sdk = genai.Client(
            api_key="test-key",
            http_options=types.HttpOptions(
                httpx_async_client=http,
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        )
        client = object.__new__(GeminiLlmClient)
        client._client = sdk
        try:
            assert await client.complete(prompt="p", response_schema={}) == {"ok": True}
        finally:
            await sdk.aio.aclose()
            sdk.close()
    assert len(requests) == 3
