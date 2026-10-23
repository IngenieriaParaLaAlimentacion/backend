from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError


def _equivalence(food_id, kind, value: str):
    """A food equivalence row with placeholder provenance."""
    from app.domain.food_catalog import EquivalenceMatchType
    from app.models.food_catalog.food_equivalence import FoodEquivalence

    return FoodEquivalence(
        food_id=food_id,
        kind=kind,
        value=Decimal(value),
        source="test",
        source_ref="test",
        match_type=EquivalenceMatchType.DIRECT,
    )


async def test_get_factors_by_food_ids_gathers_each_requested_food(foods):
    """Each requested food gets its own factors, empty when it has none, and
    foods that were not requested are left out."""
    from app.db.database import AsyncSessionLocal
    from app.domain.food_catalog import EquivalenceKind
    from app.domain.unit_conversion import ConversionFactors
    from app.repositories.food_catalog.food_equivalence_repository import (
        FoodEquivalenceRepository,
    )

    async with AsyncSessionLocal() as session:
        session.add_all(
            [
                _equivalence(foods.eggs, EquivalenceKind.DENSITY_G_ML, "1.03"),
                _equivalence(foods.eggs, EquivalenceKind.UNIT_WEIGHT_G, "50"),
            ]
        )
        await session.commit()

        repo = FoodEquivalenceRepository(session)
        both = await repo.get_factors_by_food_ids([foods.rice, foods.eggs])
        rice_only = await repo.get_factors_by_food_ids([foods.rice])
        none = await repo.get_factors_by_food_ids([])

    assert both == {
        foods.rice: ConversionFactors(),
        foods.eggs: ConversionFactors(
            density_g_ml=Decimal("1.03"), unit_weight_g=Decimal("50")
        ),
    }
    assert rice_only == {foods.rice: ConversionFactors()}
    assert none == {}


async def test_a_food_holds_one_equivalence_per_kind(foods):
    """A second factor of the same kind for the same food is rejected."""
    from app.db.database import AsyncSessionLocal
    from app.domain.food_catalog import EquivalenceKind

    async with AsyncSessionLocal() as session:
        session.add_all(
            [
                _equivalence(foods.eggs, EquivalenceKind.UNIT_WEIGHT_G, "50"),
                _equivalence(foods.eggs, EquivalenceKind.UNIT_WEIGHT_G, "60"),
            ]
        )
        with pytest.raises(IntegrityError):
            await session.commit()


@pytest.mark.parametrize("value", ["0", "-1"])
async def test_an_equivalence_value_must_be_positive(foods, value):
    """A factor that is zero or negative is rejected."""
    from app.db.database import AsyncSessionLocal
    from app.domain.food_catalog import EquivalenceKind

    async with AsyncSessionLocal() as session:
        session.add(_equivalence(foods.eggs, EquivalenceKind.UNIT_WEIGHT_G, value))
        with pytest.raises(IntegrityError):
            await session.commit()
