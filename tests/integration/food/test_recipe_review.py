"""Recipe regression coverage for snapshots, history, diagnostics and quotas."""

import json
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import structlog
from limits.aio.strategies import MovingWindowRateLimiter
from limits.storage import storage_from_string
from sqlalchemy import select, update

from app.config.settings import settings
from app.core import rate_limit
from app.domain.food_catalog import MeasurementUnit
from app.domain.user import UserRole
from app.models.food_catalog.food import Food
from app.models.food_stock.food_stock import FoodStock
from app.models.recipes.recipe import RecipeProposalRecord
from app.repositories.food_catalog.food_repository import FoodRepository
from app.repositories.food_stock.food_stock_repository import FoodStockRepository
from app.services.nutrition.nutrition_service import NutritionService
from app.services.recipes.generation import RecipeGenerator
from tests.integration.food.test_recipe_recommendations import (
    generate,
    proposal_url,
)
from tests.integration.food.test_recipe_recommendations import (
    recipe_setup as recipe_setup,
)

ROOT = "/api/v1"


async def test_flat_history_detail_and_unchosen_access(
    client, recipe_setup, make_user_with_role
):
    headers, fake, body = recipe_setup
    batches = [await generate(client, recipe_setup) for _ in range(3)]
    response = await client.get(
        f"{ROOT}/establishments/{body['establishment_id']}/recipes?page_size=3",
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["total"] == 6
    first_page = response.json()["items"]
    assert len(first_page) == 3
    second = (
        await client.get(
            f"{ROOT}/establishments/{body['establishment_id']}/recipes?page=2&page_size=3",
            headers=headers,
        )
    ).json()["items"]
    assert len({item["proposal"]["id"] for item in first_page + second}) == 6
    assert all(not item["chosen"] for item in first_page + second)
    calls = len(fake.calls)
    oldest = batches[0]
    detail_url = proposal_url(oldest).removesuffix("/choose")
    detail = await client.get(detail_url, headers=headers)
    assert detail.status_code == 200
    assert detail.json()["proposal"] == oldest["proposals"][0]
    outsider, _ = await make_user_with_role(UserRole.FIELD_WORKER)
    assert (await client.get(detail_url, headers=outsider)).status_code == 403
    assert (
        await client.get(
            f"{ROOT}/establishments/{body['establishment_id']}/recipes",
            headers=outsider,
        )
    ).status_code == 403
    assert (await client.post(proposal_url(oldest), headers=headers)).status_code == 201
    chosen = await client.get(
        f"{ROOT}/establishments/{body['establishment_id']}/recipes?chosen_only=true",
        headers=headers,
    )
    assert chosen.json()["total"] == 1
    assert chosen.json()["items"][0]["chosen"]
    assert len(fake.calls) == calls


async def test_generation_releases_connection_and_reuses_one_stock_snapshot(
    client, recipe_setup, monkeypatch
):
    from app.db.database import AsyncSessionLocal

    original_complete = RecipeGenerator._completion
    original_stock = FoodStockRepository.stocked_foods
    reads = []
    calls = []

    async def stocked(self, establishment_id):
        reads.append(establishment_id)
        return await original_stock(self, establishment_id)

    async def complete(self, *args):
        assert not self.nutrition.uow.session.in_transaction()
        calls.append(args[0])
        if len(calls) == 1:
            # A concurrent movement changes stock after the model context was built.
            async with AsyncSessionLocal() as db:
                await db.execute(update(FoodStock).values(quantity=0))
                await db.commit()
        return await original_complete(self, *args)

    monkeypatch.setattr(FoodStockRepository, "stocked_foods", stocked)
    monkeypatch.setattr(RecipeGenerator, "_completion", complete)
    monkeypatch.setattr(
        NutritionService,
        "maximize_recipe",
        AsyncMock(side_effect=AssertionError("unexpected reload")),
    )
    monkeypatch.setattr(
        FoodRepository,
        "get_with_nutrients_by_ids",
        AsyncMock(side_effect=AssertionError("unexpected nutrient query")),
    )
    result = await generate(client, recipe_setup)
    assert len(reads) == 1
    assert calls == ["selection", "writing"]
    assert all(p["ingredients"] for p in result["proposals"])
    assert (
        await client.post(proposal_url(result), headers=recipe_setup[0])
    ).status_code == 409


@pytest.mark.parametrize(
    ("mode", "slug"),
    [
        ("missing", "ingredient-unavailable"),
        ("unit", "ingredient-unit-changed"),
        ("tiny", "scale-too-small"),
    ],
)
async def test_reuse_reports_precise_ingredient_failures(
    client, recipe_setup, monkeypatch, mode, slug
):
    from app.db.database import AsyncSessionLocal

    result = await generate(client, recipe_setup)
    ingredient = result["proposals"][0]["ingredients"][0]
    if mode == "missing":
        monkeypatch.setattr(
            FoodRepository, "get_with_nutrients_by_ids", AsyncMock(return_value=[])
        )
    else:
        async with AsyncSessionLocal() as db:
            if mode == "unit":
                await db.execute(
                    update(Food)
                    .where(Food.id == ingredient["food_id"])
                    .values(base_unit=MeasurementUnit.UNIDADES)
                )
            else:
                record = (
                    await db.execute(
                        select(RecipeProposalRecord).where(
                            RecipeProposalRecord.id == result["proposals"][0]["id"]
                        )
                    )
                ).scalar_one()
                snapshot = dict(record.recipe)
                snapshot["ingredients"] = [
                    {**i, "quantity": "0.001"} for i in snapshot["ingredients"]
                ]
                record.recipe = snapshot
            await db.commit()
    response = await client.post(
        proposal_url(result, action="reuse-preview"),
        headers=recipe_setup[0],
        json={"children_count": 1},
    )
    assert response.status_code == 409
    assert response.json()["type"] == f"/errors/recipes/{slug}"
    assert response.json()["ingredient"] == ingredient["name"]
    assert response.json()["food_id"] == ingredient["food_id"]


@pytest.mark.parametrize(
    ("mode", "stage", "reason"),
    [
        ("error", "selection", "provider_failure"),
        ("invalid_candidates", "selection", "insufficient_valid_proposals"),
        ("invalid_writing", "writing", "ingredient_references_mismatch"),
    ],
)
async def test_generation_failure_logs_are_actionable_and_do_not_dump_context(
    client, recipe_setup, mode, stage, reason
):
    headers, fake, body = recipe_setup
    setattr(fake, mode, True)
    with structlog.testing.capture_logs() as logs:
        response = await client.post(
            f"{ROOT}/recipe-recommendations", headers=headers, json=body
        )
    assert response.status_code == 502
    failures = [log for log in logs if log["event"] == "recipes.generation_failed"]
    assert failures[-1]["stage"] == stage
    assert failures[-1]["reason"] == reason
    assert failures[-1]["prompt_version"] == "v1"
    assert set(failures[-1]) <= {
        "event",
        "log_level",
        "stage",
        "reason",
        "prompt_version",
        "failures",
    }
    assert str(body["establishment_id"]) not in json.dumps(failures)


async def test_ai_quota_is_shared_across_endpoints_and_separate_for_each_user(
    client, recipe_setup, monkeypatch, make_user_with_role
):
    headers, fake, body = recipe_setup
    memory = MovingWindowRateLimiter(storage_from_string("async+memory://"))
    monkeypatch.setattr(
        rate_limit, "_limiter", rate_limit.ResilientLimiter(memory, memory)
    )
    monkeypatch.setattr(settings, "rate_limit_ai_user", "1/hour")
    await generate(client, recipe_setup)
    count = len(fake.calls)
    response = await client.post(
        f"{ROOT}/recipe-recommendations", headers=headers, json=body
    )
    assert response.status_code == 429
    assert "retry-after" in response.headers
    assert len(fake.calls) == count
    # Receipt extraction has the same quota even though it uses another model flow.
    response = await client.post(
        f"{ROOT}/food-intakes/from-photo",
        headers=headers,
        data={"establishment_id": body["establishment_id"]},
        files={"image": ("receipt.png", b"not an image", "image/png")},
    )
    assert response.status_code == 429
    other, _ = await make_user_with_role(UserRole.ADMIN)
    response = await client.post(
        f"{ROOT}/recipe-recommendations", headers=other, json=body
    )
    assert response.status_code == 201


@pytest.mark.parametrize(
    ("mode", "reason"),
    [
        ("timeout", "provider_timeout"),
        ("ids", "proposal_ids_mismatch"),
        ("amounts", "quantities_in_prose"),
        ("duplicate", "duplicate_preparation"),
        ("schema", "schema_validation"),
        ("culture", "culture_mismatch"),
    ],
)
async def test_writing_and_transport_failure_reasons(
    client, recipe_setup, mode, reason
):
    from app.exceptions.domain_exceptions import LlmClientError

    headers, fake, body = recipe_setup
    original = fake.complete

    async def changed(**kwargs):
        if mode == "timeout":
            try:
                raise TimeoutError("sensitive context must not be logged")
            except TimeoutError as cause:
                raise LlmClientError("sensitive provider message") from cause
        result = await original(**kwargs)
        if "recipes" not in result:
            return result
        if mode == "ids":
            result["recipes"][0]["proposal_id"] = str(uuid4())
        elif mode == "amounts":
            result["recipes"][0]["steps"][0]["text"] = "Agregar 10 gramos."
        elif mode == "duplicate":
            # Identical ingredient set + preparation must be rejected.
            result["recipes"][1]["steps"] = result["recipes"][0]["steps"]
        elif mode == "schema":
            result["recipes"] = []
        elif mode == "culture":
            result["recipes"][0]["cultural_identity"] = "guarani"
        return result

    if mode == "duplicate":
        fake.single_food = True
    fake.complete = changed
    with structlog.testing.capture_logs() as logs:
        response = await client.post(
            f"{ROOT}/recipe-recommendations", headers=headers, json=body
        )
    assert response.status_code == 502
    failure = [log for log in logs if log["event"] == "recipes.generation_failed"][-1]
    assert failure["reason"] == reason
    assert "sensitive" not in json.dumps(logs)


async def test_generation_deadline_returns_504_without_partial_records(
    client, recipe_setup, monkeypatch
):
    import asyncio

    from tests.integration.food.test_recipe_recommendations import counts

    headers, fake, body = recipe_setup
    monkeypatch.setattr(settings, "recipe_generation_timeout_seconds", 0.1)

    async def blocked(**_):
        await asyncio.Event().wait()

    fake.complete = blocked
    response = await asyncio.wait_for(
        client.post(f"{ROOT}/recipe-recommendations", headers=headers, json=body),
        timeout=2,
    )
    assert response.status_code == 504
    assert response.json()["type"] == "/errors/recipes/generation-timeout"
    assert await counts() == [0, 0, 0]
