import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from google.genai.errors import ClientError, ServerError

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
