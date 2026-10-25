"""Recipe amount detection and request-wide deadline regressions."""

import asyncio
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import structlog

from app.config.settings import settings
from app.domain.user import UserActor, UserRole
from app.exceptions.domain_exceptions import RecipeGenerationTimeoutError
from app.schemas.recipes.recipe_schema import RecommendationInput
from app.services.recipes.generation import _AMOUNT_IN_PROSE
from app.services.recipes.recipe_service import RecipeService


@pytest.mark.parametrize(
    "text",
    [
        "Agregar 2 kilos de arroz.",
        "Usar un kilo de arroz.",
        "Agregar dos tazas.",
        "Agregar dos cucharaditas de sal.",
        "Sumar 250 cc de leche.",
        "Agregar 1 l de leche.",
        "Usar tres latas.",
        "Agregar un vaso de leche.",
        "Agregar 1/2 taza.",
        "Agregar ½ taza.",
        "Usar media taza.",
        "Agregar un cuarto de kilo.",
        "Agregar dos y media tazas.",
        "Agregar ciento cincuenta gramos.",
        "Sumar veintidós gramos.",
        "Agregar 10ml.",
        "Agregar 2 cdas de aceite.",
        "Usar una unidad.",
        "Agregar doscientos gramos.",
    ],
)
def test_amounts_in_spanish_are_rejected(text):
    assert _AMOUNT_IN_PROSE.search(text)


@pytest.mark.parametrize(
    "text",
    [
        "Hornear a 200 °C.",
        "Cocinar entre 15 y 20 minutos.",
        "Dejar reposar media hora.",
        "Cocinar por veinte minutos.",
        "Mezclar y servir en una fuente.",
        "Rallar las zanahorias.",
        "Calentar hasta 80 grados.",
        "Servir en vasos individuales.",
    ],
)
def test_times_temperatures_and_unquantified_preparation_are_allowed(text):
    assert not _AMOUNT_IN_PROSE.search(text)


async def test_total_generation_deadline_cancels_work_and_rolls_back(monkeypatch):
    monkeypatch.setattr(settings, "recipe_generation_timeout_seconds", 0.02)
    uow = AsyncMock()
    service = RecipeService(uow)
    cancelled = asyncio.Event()

    async def blocked(*_):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    service._generate = blocked
    data = RecommendationInput(
        establishment_id=uuid4(), children_count=30, meal_type="lunch"
    )
    actor = UserActor(user_id=uuid4(), role=UserRole.ADMIN)
    with structlog.testing.capture_logs() as logs:
        with pytest.raises(RecipeGenerationTimeoutError):
            await asyncio.wait_for(service.generate(data, actor), timeout=1)
    assert cancelled.is_set()
    uow.rollback.assert_awaited_once()
    assert logs[-1]["reason"] == "total_deadline_exceeded"
    assert logs[-1]["stage"] == "request"


async def test_external_cancellation_is_not_changed_to_a_timeout():
    service = RecipeService(AsyncMock())
    service._generate = AsyncMock(side_effect=asyncio.CancelledError)
    with pytest.raises(asyncio.CancelledError):
        await service.generate(None, None)


async def test_request_deadline_includes_backoff_and_prevents_fallback(monkeypatch):
    from unittest.mock import Mock

    from google.genai.errors import ServerError

    from app.services.llm.gemini_llm_client import GeminiLlmClient

    monkeypatch.setattr(settings, "recipe_generation_timeout_seconds", 0.02)
    monkeypatch.setattr(settings, "gemini_retry_backoff_initial_seconds", 1)
    monkeypatch.setattr(settings, "gemini_retry_backoff_max_seconds", 1)
    monkeypatch.setattr(settings, "gemini_max_attempts", 3)
    monkeypatch.setattr(settings, "gemini_fallback_model", "fallback-model")
    client = object.__new__(GeminiLlmClient)
    client._client = Mock()
    client._client.aio.models.generate_content = AsyncMock(
        side_effect=ServerError(503, {"message": "busy"})
    )
    service = RecipeService(AsyncMock())

    async def generate(*_):
        return await client.complete(prompt="p", response_schema={})

    service._generate = generate
    with pytest.raises(RecipeGenerationTimeoutError):
        await asyncio.wait_for(service.generate(None, None), timeout=1)
    assert client._client.aio.models.generate_content.await_count == 1
