"""App-scoped OpenRouter client reuse and shutdown cleanup."""

from unittest.mock import AsyncMock, Mock, patch

import httpx
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.config.settings import Settings
from app.core.dependencies import get_llm_client
from app.main import app
from app.services.llm.openrouter_llm_client import OpenRouterLlmClient


async def test_dependency_reuses_client_within_app_but_not_across_apps():
    first, other = FastAPI(), FastAPI()

    def request(application):
        return Request({"type": "http", "app": application})

    with patch("app.core.dependencies.OpenRouterLlmClient") as factory:
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


async def test_unconfigured_client_never_requests_and_closes_once():
    requests = []
    closes = []

    class CountingTransport(httpx.MockTransport):
        async def aclose(self):
            closes.append(True)
            await super().aclose()

    client = OpenRouterLlmClient(
        settings=Settings(
            _env_file=None,
            openrouter_api_key=None,
            openrouter_receipt_models=[],
            openrouter_recipe_models=[],
        ),
        transport=CountingTransport(lambda request: requests.append(request)),
    )
    assert requests == []
    assert not client._http.is_closed
    await client.aclose()
    await client.aclose()
    assert client._http.is_closed
    assert closes == [True]


async def test_cached_dependency_without_ai_config_never_contacts_gateway():
    application = FastAPI()
    request = Request({"type": "http", "app": application})
    with (
        patch(
            "app.core.dependencies.settings",
            Settings(
                _env_file=None,
                openrouter_api_key=None,
                openrouter_receipt_models=[],
                openrouter_recipe_models=[],
                openrouter_allowed_providers=[],
            ),
        ),
        patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as get,
        patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as post,
    ):
        client = await get_llm_client(request)
        try:
            assert await get_llm_client(request) is client
            get.assert_not_awaited()
            post.assert_not_awaited()
        finally:
            await client.aclose()


def test_shutdown_continues_when_client_close_fails():
    client = Mock(aclose=AsyncMock(side_effect=RuntimeError("close failed")))
    with (
        patch("app.main.telemetry") as telemetry,
        patch("app.main.engine") as engine,
        patch("app.main.StaleEstablishmentScheduler") as scheduler,
        patch("app.main.close_limiter", new_callable=AsyncMock) as close_limiter,
    ):
        engine.dispose = AsyncMock()
        scheduler.return_value.shutdown = AsyncMock()
        with TestClient(app):
            app.state.llm_client = client
        client.aclose.assert_awaited_once()
        assert app.state.llm_client is None
        engine.dispose.assert_awaited_once()
        close_limiter.assert_awaited_once()
        telemetry.tracer_provider.shutdown.assert_called_once()
        telemetry.meter_provider.shutdown.assert_called_once()
        telemetry.logger_provider.shutdown.assert_called_once()
