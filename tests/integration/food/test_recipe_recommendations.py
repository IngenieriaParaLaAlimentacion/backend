import asyncio
import json
from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import func, select, update

from app.core.dependencies import get_llm_client
from app.core.interfaces.llm_client import ILlmClient
from app.domain.food_catalog import (
    EquivalenceKind,
    EquivalenceMatchType,
    NutrientGroup,
)
from app.domain.user import UserRole
from app.exceptions.domain_exceptions import (
    LlmClientError,
    LlmQuotaExhaustedError,
    LlmUnavailableError,
)
from app.models.food_catalog.food_equivalence import FoodEquivalence
from app.models.food_catalog.food_nutrient_value import FoodNutrientValue
from app.models.food_catalog.nutrient import Nutrient
from app.models.food_outflows.food_outflow import FoodOutflow
from app.models.food_stock.food_stock import FoodStock
from app.models.recipes.recipe import RecipeRequestRecord, RecipeSelection

ROOT = "/api/v1"


class RecipeLlm(ILlmClient):
    """Script structured responses from the actual workflow context."""

    def __init__(self, foods):
        self.foods = foods
        self.calls = []
        self.error = False
        self.outside = False
        self.invalid_writing = False
        self.invalid_candidates = False
        self.repair_first = False
        self.cultural_fallback = False
        self.single_food = False

    async def complete(self, *, prompt, **kwargs):
        self.calls.append(prompt)
        if isinstance(self.error, Exception):
            raise self.error
        if self.error:
            raise LlmClientError("provider unavailable")
        context = json.loads(prompt.split("Context:\n")[1])
        if "recipes" not in context:
            if self.invalid_candidates or self.repair_first and len(self.calls) == 1:
                return {"cultural_dish_viable": False, "candidates": []}
            return {
                "cultural_dish_viable": bool(context["cultural_identities"])
                and not self.cultural_fallback,
                "candidates": [
                    {
                        "concept": name,
                        "food_ids": [str(food_id)]
                        + ([str(uuid4())] if self.outside else []),
                        "cultural_identity": context["cultural_identities"][0]
                        if index == 0
                        and context["cultural_identities"]
                        and not self.cultural_fallback
                        else None,
                    }
                    for index, (name, food_id) in enumerate(
                        [
                            ("Arroz", self.foods.rice),
                            ("Arroz tostado", self.foods.rice)
                            if self.single_food
                            else ("Huevos", self.foods.eggs),
                        ]
                    )
                ],
            }
        return {
            "recipes": [
                {
                    "proposal_id": p["id"],
                    "name": p["name"],
                    "steps": [
                        {
                            "text": "Tostar y servir."
                            if p["name"] == "Arroz tostado"
                            else "Preparar y servir.",
                            "food_ids": [str(uuid4())]
                            if self.invalid_writing
                            else [i["food_id"] for i in p["ingredients"]],
                        }
                    ],
                    "cultural_identity": p["cultural_identity"],
                    "quantity": 999999,
                }
                for p in context["recipes"]
            ]
        }


@pytest_asyncio.fixture
async def recipe_setup(app, foods, db_establishment, make_user_with_role):
    from app.db.database import AsyncSessionLocal

    headers, _ = await make_user_with_role(UserRole.ADMIN)
    async with AsyncSessionLocal() as db:
        energy = Nutrient(
            code="valor_energetico",
            name="Energy",
            unit="kcal",
            group=NutrientGroup.MACRONUTRIENT,
        )
        db.add(energy)
        await db.flush()
        db.add_all(
            [
                FoodNutrientValue(
                    food_id=foods.rice, nutrient_id=energy.id, amount_per_100g=360
                ),
                FoodNutrientValue(
                    food_id=foods.eggs, nutrient_id=energy.id, amount_per_100g=150
                ),
                FoodStock(
                    establishment_id=db_establishment.id,
                    food_id=foods.rice,
                    quantity=Decimal("2"),
                ),
                FoodStock(
                    establishment_id=db_establishment.id,
                    food_id=foods.eggs,
                    quantity=Decimal("20"),
                ),
                FoodEquivalence(
                    food_id=foods.eggs,
                    kind=EquivalenceKind.UNIT_WEIGHT_G,
                    value=Decimal("50"),
                    source="test",
                    source_ref="test",
                    match_type=EquivalenceMatchType.DIRECT,
                ),
            ]
        )
        await db.commit()
    fake = RecipeLlm(foods)
    app.dependency_overrides[get_llm_client] = lambda: fake
    yield (
        headers,
        fake,
        {
            "establishment_id": str(db_establishment.id),
            "children_count": 30,
            "meal_type": "lunch",
        },
    )
    app.dependency_overrides.pop(get_llm_client, None)


async def generate(client, setup):
    headers, _, body = setup
    response = await client.post(
        f"{ROOT}/recipe-recommendations", headers=headers, json=body
    )
    assert response.status_code == 201, response.text
    return response.json()


def proposal_url(result, index=0, action="choose"):
    proposal_id = result["proposals"][index]["id"]
    base = f"{ROOT}/recipe-recommendations/{result['id']}"
    return f"{base}/proposals/{proposal_id}/{action}"


async def counts():
    from app.db.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        return [
            await db.scalar(select(func.count()).select_from(model))
            for model in (RecipeRequestRecord, RecipeSelection, FoodOutflow)
        ]


async def test_generation_history_choice_and_replay(client, recipe_setup):
    headers, fake, body = recipe_setup
    result = await generate(client, recipe_setup)
    assert len(fake.calls) == 2
    assert len(result["proposals"]) == 2
    assert result["selection"] is None
    assert all(p["unmet_constraints"] for p in result["proposals"])
    assert (
        result["proposals"][0]["energy_kcal"]
        < result["proposals"][0]["target_energy_kcal"]
    )
    assert await counts() == [1, 0, 0]
    first = await client.post(proposal_url(result), headers=headers)
    assert first.status_code == 201, first.text
    second = await client.post(proposal_url(result), headers=headers)
    assert second.status_code == 200
    assert first.json() == second.json()
    assert await counts() == [1, 1, 1]
    other = await client.post(proposal_url(result, 1), headers=headers)
    assert other.status_code == 409
    history = await client.get(
        f"{ROOT}/establishments/{body['establishment_id']}/recipe-recommendations?chosen_only=true&page_size=1",
        headers=headers,
    )
    assert history.status_code == 200
    assert history.json()["total"] == 1
    assert len(history.json()["items"][0]["proposals"]) == 1
    assert len(fake.calls) == 2


async def test_outside_stock_food_is_discarded(client, recipe_setup, foods):
    recipe_setup[1].outside = True
    result = await generate(client, recipe_setup)
    assert {i["food_id"] for p in result["proposals"] for i in p["ingredients"]} == {
        str(foods.rice),
        str(foods.eggs),
    }


@pytest.mark.parametrize("mode", ["error", "invalid_writing", "invalid_candidates"])
async def test_model_failure_never_saves_partial_proposals(client, recipe_setup, mode):
    headers, fake, body = recipe_setup
    setattr(fake, mode, True)
    response = await client.post(
        f"{ROOT}/recipe-recommendations", headers=headers, json=body
    )
    assert response.status_code == 502, response.text
    assert response.json()["type"] == "/errors/recipes/generation-failed"
    assert len(fake.calls) <= 3
    assert await counts() == [0, 0, 0]


async def test_empty_stock_does_not_call_model(client, recipe_setup):
    from app.db.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        await db.execute(update(FoodStock).values(quantity=0))
        await db.commit()
    headers, fake, body = recipe_setup
    response = await client.post(
        f"{ROOT}/recipe-recommendations", headers=headers, json=body
    )
    assert response.status_code == 409
    assert fake.calls == []


async def test_stock_changed_since_generation_rolls_back_choice(client, recipe_setup):
    from app.db.database import AsyncSessionLocal

    result = await generate(client, recipe_setup)
    async with AsyncSessionLocal() as db:
        await db.execute(update(FoodStock).values(quantity=0))
        await db.commit()
    response = await client.post(proposal_url(result), headers=recipe_setup[0])
    assert response.status_code == 409, response.text
    assert "available" in response.json()
    assert await counts() == [1, 0, 0]


async def test_reuse_scales_and_is_idempotent_without_model(client, recipe_setup):
    result = await generate(client, recipe_setup)
    headers, fake, _ = recipe_setup
    payload = {"id": str(uuid4()), "children_count": 15}
    response = await client.post(
        proposal_url(result, action="reuse"), headers=headers, json=payload
    )
    assert response.status_code == 201, response.text
    reused = response.json()
    assert reused["id"] == payload["id"]
    assert reused["proposals"][0]["portions"] == 15
    original_quantity = Decimal(result["proposals"][0]["ingredients"][0]["quantity"])
    assert (
        Decimal(reused["proposals"][0]["ingredients"][0]["quantity"])
        == original_quantity / 2
    )
    replay = await client.post(
        proposal_url(result, action="reuse"), headers=headers, json=payload
    )
    assert replay.status_code == 200
    assert replay.json() == reused
    conflict = await client.post(
        proposal_url(result, action="reuse"),
        headers=headers,
        json={**payload, "children_count": 16},
    )
    assert conflict.status_code == 409
    assert len(fake.calls) == 2
    assert await counts() == [2, 1, 1]


async def test_access_denied_for_generation_history_and_choice(
    client, recipe_setup, make_user_with_role
):
    result = await generate(client, recipe_setup)
    headers, _ = await make_user_with_role(UserRole.FIELD_WORKER)
    _, fake, body = recipe_setup
    responses = [
        await client.post(f"{ROOT}/recipe-recommendations", headers=headers, json=body),
        await client.post(proposal_url(result), headers=headers),
        await client.get(
            f"{ROOT}/establishments/{body['establishment_id']}/recipe-recommendations",
            headers=headers,
        ),
    ]
    assert [r.status_code for r in responses] == [403, 403, 403]
    assert len(fake.calls) == 2


async def test_analyst_requires_subscription(client, recipe_setup, make_user_with_role):
    headers, _ = await make_user_with_role(UserRole.ANALYST)
    response = await client.post(
        f"{ROOT}/recipe-recommendations", headers=headers, json=recipe_setup[2]
    )
    assert response.status_code == 403
    assert recipe_setup[1].calls == []


async def test_missing_establishment_precedes_model(client, recipe_setup):
    response = await client.post(
        f"{ROOT}/recipe-recommendations",
        headers=recipe_setup[0],
        json={**recipe_setup[2], "establishment_id": str(uuid4())},
    )
    assert response.status_code == 404
    assert recipe_setup[1].calls == []


@pytest.mark.parametrize("value", [0, -1, True, 2.5, "3", 10001])
async def test_invalid_children_count(client, recipe_setup, value):
    response = await client.post(
        f"{ROOT}/recipe-recommendations",
        headers=recipe_setup[0],
        json={**recipe_setup[2], "children_count": value},
    )
    assert response.status_code == 422
    assert recipe_setup[1].calls == []


@pytest.mark.parametrize(
    "identity",
    [
        "paraguayan",
        "bolivian",
        "guarani",
        "andean",
        "indigenous",
        "migrant",
        "criollo",
        "other",
    ],
)
async def test_culture_from_characterization(
    client, recipe_setup, identity, field_worker_with_access, make_user_with_role
):
    headers, fake, body = recipe_setup
    url = f"{ROOT}/establishments/{body['establishment_id']}/characterization"
    result = await generate(client, recipe_setup)
    assert all(p["cultural_identity"] is None for p in result["proposals"])
    profile = {"cultural_identities": [identity]}
    if identity == "other":
        profile["cultural_identities_other"] = "Cocina peruana"
    field_headers, _ = field_worker_with_access
    response = await client.put(url, headers=field_headers, json=profile)
    assert response.status_code == 200
    result = await generate(client, recipe_setup)
    assert result["proposals"][0]["cultural_identity"] == identity
    for prompt in fake.calls[-2:]:
        context = json.loads(prompt.split("Context:\n")[1])
        assert context["cultural_identities"] == [identity]
        assert context["cultural_identities_other"] == profile.get(
            "cultural_identities_other"
        )
    outsider, _ = await make_user_with_role(UserRole.FIELD_WORKER)
    assert (await client.put(url, headers=outsider, json={})).status_code == 403
    assert (
        await client.put(
            url, headers=headers, json={"cultural_identities": ["invented"]}
        )
    ).status_code == 422
    assert (await client.put(url, headers=headers, json={})).status_code == 200
    result = await generate(client, recipe_setup)
    assert all(p["cultural_identity"] is None for p in result["proposals"])
    assert (
        json.loads(fake.calls[-1].split("Context:\n")[1])["cultural_identities_other"]
        is None
    )


async def test_concurrent_identical_choices_spend_once(client, recipe_setup):
    result = await generate(client, recipe_setup)
    responses = await asyncio.gather(
        *[client.post(proposal_url(result), headers=recipe_setup[0]) for _ in range(2)]
    )
    assert sorted(r.status_code for r in responses) == [200, 201], [
        r.text for r in responses
    ]
    assert responses[0].json() == responses[1].json()
    assert await counts() == [1, 1, 1]


async def test_concurrent_different_choices_select_only_one(client, recipe_setup):
    result = await generate(client, recipe_setup)
    responses = await asyncio.gather(
        *[
            client.post(proposal_url(result, index=i), headers=recipe_setup[0])
            for i in (0, 1)
        ]
    )
    assert sorted(r.status_code for r in responses) == [201, 409], [
        r.text for r in responses
    ]
    assert await counts() == [1, 1, 1]


async def test_single_repair_then_success(client, recipe_setup):
    recipe_setup[1].repair_first = True
    result = await generate(client, recipe_setup)
    assert len(result["proposals"]) == 2
    assert len(recipe_setup[1].calls) == 3


async def test_cultural_dish_not_viable_uses_ordinary_meals(client, recipe_setup):
    headers, fake, body = recipe_setup
    fake.cultural_fallback = True
    await client.put(
        f"{ROOT}/establishments/{body['establishment_id']}/characterization",
        headers=headers,
        json={"cultural_identities": ["paraguayan"]},
    )
    result = await generate(client, recipe_setup)
    assert all(p["cultural_identity"] is None for p in result["proposals"])
    assert len(fake.calls) == 2


async def test_reuse_stock_shortfall_saves_nothing(client, recipe_setup):
    result = await generate(client, recipe_setup)
    response = await client.post(
        proposal_url(result, action="reuse"),
        headers=recipe_setup[0],
        json={"id": str(uuid4()), "children_count": 10000},
    )
    assert response.status_code == 409, response.text
    assert await counts() == [1, 0, 0]
    assert len(recipe_setup[1].calls) == 2


async def test_concurrent_identical_reuse_spends_once(client, recipe_setup):
    result = await generate(client, recipe_setup)
    data = {"id": str(uuid4()), "children_count": 15}
    responses = await asyncio.gather(
        *[
            client.post(
                proposal_url(result, action="reuse"), headers=recipe_setup[0], json=data
            )
            for _ in range(2)
        ]
    )
    assert sorted(r.status_code for r in responses) == [200, 201], [
        r.text for r in responses
    ]
    assert responses[0].json() == responses[1].json()
    assert await counts() == [2, 1, 1]


async def test_distinct_preparations_can_share_the_same_ingredient(
    client, recipe_setup
):
    recipe_setup[1].single_food = True
    result = await generate(client, recipe_setup)
    first, second = result["proposals"]
    assert first["ingredients"] == second["ingredients"]
    assert first["steps"] != second["steps"]
    assert len(first["ingredients"]) == 1


async def test_reuse_preview_is_read_only_and_matches_confirmed_amounts(
    client, recipe_setup
):
    result = await generate(client, recipe_setup)
    response = await client.post(
        proposal_url(result, action="reuse-preview"),
        headers=recipe_setup[0],
        json={"children_count": 15},
    )
    assert response.status_code == 200, response.text
    assert response.json()["portions"] == 15
    assert await counts() == [1, 0, 0]
    chosen = await client.post(
        proposal_url(result, action="reuse"),
        headers=recipe_setup[0],
        json={"id": str(uuid4()), "children_count": 15},
    )
    assert chosen.status_code == 201, chosen.text
    assert (
        chosen.json()["proposals"][0]["ingredients"] == response.json()["ingredients"]
    )
    assert len(recipe_setup[1].calls) == 2


async def test_reuse_preview_insufficient_stock_saves_nothing(client, recipe_setup):
    result = await generate(client, recipe_setup)
    response = await client.post(
        proposal_url(result, action="reuse-preview"),
        headers=recipe_setup[0],
        json={"children_count": 10000},
    )
    assert response.status_code == 409
    assert await counts() == [1, 0, 0]


async def test_recipe_specific_culture_endpoints_are_absent(client, recipe_setup):
    headers, _, body = recipe_setup
    response = await client.get(f"{ROOT}/cultural-identities", headers=headers)
    assert response.status_code == 404
    url = f"{ROOT}/establishments/{body['establishment_id']}/cultural-identities"
    assert (await client.get(url, headers=headers)).status_code == 404
    assert (
        await client.put(url, headers=headers, json={"identities": []})
    ).status_code == 404


@pytest.mark.parametrize(
    "failure,status,slug,delay",
    [
        (LlmQuotaExhaustedError(12), 429, "ai/quota-exhausted", 12),
        (LlmQuotaExhaustedError(), 429, "ai/quota-exhausted", None),
        (LlmUnavailableError("private provider failure"), 503, "ai/unavailable", None),
    ],
)
async def test_provider_failure_preserves_stock_and_has_no_partial_records(
    client,
    recipe_setup,
    failure,
    status,
    slug,
    delay,
):
    from app.db.database import AsyncSessionLocal
    from app.models.recipes.recipe import RecipeProposalRecord

    async def stock():
        async with AsyncSessionLocal() as db:
            return dict(
                (await db.execute(select(FoodStock.food_id, FoodStock.quantity))).all()
            )

    headers, fake, body = recipe_setup
    before = await stock()
    fake.error = failure
    response = await client.post(
        f"{ROOT}/recipe-recommendations", headers=headers, json=body
    )
    assert response.status_code == status
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["type"] == f"/errors/{slug}"
    assert "private" not in response.text
    assert len(fake.calls) == 1
    assert await counts() == [0, 0, 0]
    assert await stock() == before
    async with AsyncSessionLocal() as db:
        assert (
            await db.scalar(select(func.count()).select_from(RecipeProposalRecord)) == 0
        )
    if delay:
        assert response.headers["retry-after"] == str(delay)
        assert response.json()["retry_after"] == delay
    else:
        assert "retry-after" not in response.headers
        assert "retry_after" not in response.json()
