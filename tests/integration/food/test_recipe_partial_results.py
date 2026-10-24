"""Keep independently valid alternatives without extra model calls."""

from uuid import uuid4

import pytest

from app.services.recipes.generation import (
    CULTURAL_UNAVAILABLE_WARNING,
    FEWER_ALTERNATIVES_WARNING,
)
from tests.integration.food.test_recipe_recommendations import (
    counts,
    generate,
    proposal_url,
)
from tests.integration.food.test_recipe_recommendations import (
    recipe_setup as recipe_setup,
)

ROOT = "/api/v1"


@pytest.mark.parametrize("reported_viable", [True, False])
async def test_missing_cultural_recipe_returns_valid_alternatives_without_repair(
    client, recipe_setup, reported_viable
):
    headers, fake, body = recipe_setup
    response = await client.put(
        f"{ROOT}/establishments/{body['establishment_id']}/characterization",
        headers=headers,
        json={"cultural_identities": ["paraguayan"]},
    )
    assert response.status_code == 200
    original = fake.complete

    async def ordinary(**kwargs):
        result = await original(**kwargs)
        if "candidates" in result:
            result["cultural_dish_viable"] = reported_viable
            for candidate in result["candidates"]:
                candidate["cultural_identity"] = None
        return result

    fake.complete = ordinary
    result = await generate(client, recipe_setup)
    assert len(result["proposals"]) == 2
    assert all(p["cultural_identity"] is None for p in result["proposals"])
    assert all(
        CULTURAL_UNAVAILABLE_WARNING in p["warnings"] for p in result["proposals"]
    )
    assert len(fake.calls) == 2
    assert await counts() == [1, 0, 0]


@pytest.mark.parametrize(
    "mode", ["schema", "references", "quantity", "missing", "unknown", "duplicate_id"]
)
async def test_one_valid_writing_survives_and_can_be_chosen(client, recipe_setup, mode):
    headers, fake, body = recipe_setup
    original = fake.complete

    async def partly_invalid(**kwargs):
        result = await original(**kwargs)
        if "recipes" not in result:
            return result
        first = result["recipes"][0]
        if mode == "schema":
            first["steps"] = []
        elif mode == "references":
            first["steps"][0]["food_ids"] = [str(uuid4())]
        elif mode == "quantity":
            first["steps"][0]["text"] = "Agregar dos kilos de arroz."
        elif mode == "missing":
            result["recipes"] = result["recipes"][1:]
        elif mode == "unknown":
            first["proposal_id"] = str(uuid4())
        else:
            result["recipes"][1]["proposal_id"] = first["proposal_id"]
        return result

    fake.complete = partly_invalid
    result = await generate(client, recipe_setup)
    assert len(result["proposals"]) == 1
    assert FEWER_ALTERNATIVES_WARNING in result["proposals"][0]["warnings"]
    assert len(fake.calls) == 2
    history = await client.get(
        f"{ROOT}/establishments/{body['establishment_id']}/recipe-recommendations",
        headers=headers,
    )
    assert history.json()["items"][0]["proposals"] == result["proposals"]
    chosen = await client.post(proposal_url(result), headers=headers)
    assert chosen.status_code == 201
    replay = await client.post(proposal_url(result), headers=headers)
    assert replay.json() == chosen.json()
    assert len(fake.calls) == 2
    assert await counts() == [1, 1, 1]


async def test_invalid_cultural_writing_does_not_remove_valid_ordinary_recipe(
    client, recipe_setup
):
    headers, fake, body = recipe_setup
    await client.put(
        f"{ROOT}/establishments/{body['establishment_id']}/characterization",
        headers=headers,
        json={"cultural_identities": ["paraguayan"]},
    )
    original = fake.complete

    async def changed(**kwargs):
        result = await original(**kwargs)
        if "recipes" in result:
            result["recipes"][0]["steps"] = []
        return result

    fake.complete = changed
    result = await generate(client, recipe_setup)
    assert len(result["proposals"]) == 1
    assert result["proposals"][0]["cultural_identity"] is None
    assert set(result["proposals"][0]["warnings"]) >= {
        CULTURAL_UNAVAILABLE_WARNING,
        FEWER_ALTERNATIVES_WARNING,
    }
    assert len(fake.calls) == 2


@pytest.mark.parametrize("mode", ["only_one", "invalid_sibling"])
async def test_single_valid_candidate_is_not_repaired_to_fill_count(
    client, recipe_setup, mode
):
    original = recipe_setup[1].complete

    async def changed(**kwargs):
        result = await original(**kwargs)
        if "candidates" in result:
            if mode == "only_one":
                result["candidates"] = result["candidates"][:1]
            else:
                result["candidates"][1]["food_ids"] = ["bad-uuid"]
        return result

    recipe_setup[1].complete = changed
    result = await generate(client, recipe_setup)
    assert len(result["proposals"]) == 1
    assert FEWER_ALTERNATIVES_WARNING in result["proposals"][0]["warnings"]
    assert len(recipe_setup[1].calls) == 2


async def test_valid_sibling_is_kept_when_other_item_is_not_an_object(
    client, recipe_setup
):
    original = recipe_setup[1].complete

    async def changed(**kwargs):
        result = await original(**kwargs)
        if "recipes" in result:
            result["recipes"][0] = "not a recipe"
        return result

    recipe_setup[1].complete = changed
    result = await generate(client, recipe_setup)
    assert len(result["proposals"]) == 1
    assert len(recipe_setup[1].calls) == 2


async def test_no_valid_writing_fails_without_persisting_or_retrying(
    client, recipe_setup
):
    recipe_setup[1].invalid_writing = True
    response = await client.post(
        f"{ROOT}/recipe-recommendations", headers=recipe_setup[0], json=recipe_setup[2]
    )
    assert response.status_code == 502
    assert len(recipe_setup[1].calls) == 2
    assert await counts() == [0, 0, 0]
