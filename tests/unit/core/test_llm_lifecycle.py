"""One Gemini client per application, closed on shutdown including cleanup errors."""

from unittest.mock import AsyncMock, Mock, patch

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.core.dependencies import get_llm_client
from app.main import app
from app.services.llm.gemini_llm_client import GeminiLlmClient


async def test_dependency_reuses_client_within_app_but_not_across_apps():
    first, other = FastAPI(), FastAPI()

    def request(application):
        return Request({"type": "http", "app": application})

    with patch("app.core.dependencies.GeminiLlmClient") as factory:
        factory.side_effect = [Mock(), Mock()]
        one = await get_llm_client(request(first))
        assert await get_llm_client(request(first)) is one
        assert await get_llm_client(request(other)) is not one
        assert factory.call_count == 2


def test_lifespan_closes_shared_client_and_resets_state():
    client = Mock(aclose=AsyncMock())
    with (
        patch("app.main.telemetry"),
        patch("app.main.engine") as engine,
        patch("app.main.StaleEstablishmentScheduler") as scheduler,
    ):
        engine.dispose = AsyncMock()
        scheduler.return_value.shutdown = AsyncMock()
        with TestClient(app):
            assert app.state.llm_client is None
            app.state.llm_client = client
        client.aclose.assert_awaited_once()
        assert app.state.llm_client is None
        engine.dispose.assert_awaited_once()


async def test_client_closes_owned_http_even_when_sdk_close_fails():
    client = object.__new__(GeminiLlmClient)
    client._client = Mock()
    client._client.aio.aclose = AsyncMock(side_effect=RuntimeError("close failed"))
    client._http_client = Mock(aclose=AsyncMock())
    import pytest

    with pytest.raises(RuntimeError):
        await client.aclose()
    client._client.close.assert_called_once()
    client._http_client.aclose.assert_awaited_once()
