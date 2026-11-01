import pytest_asyncio

from app.core.dependencies import get_llm_client
from app.domain.food_catalog import NutrientGroup
from app.domain.user import UserRole
from tests.integration.nutrition_reports.helpers import (
    MARCH_INTAKE,
    ReportLlm,
    add_intake,
)


@pytest_asyncio.fixture
async def report_llm(app):
    """Replace the AI client with a scripted one for the length of the test."""
    fake = ReportLlm()
    app.dependency_overrides[get_llm_client] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_llm_client, None)


@pytest_asyncio.fixture
async def energy_values(foods):
    """Give the seeded foods the energy the monthly balance needs."""
    from app.db.database import AsyncSessionLocal
    from app.models.food_catalog.food_nutrient_value import FoodNutrientValue
    from app.models.food_catalog.nutrient import Nutrient

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
            ]
        )
        await db.commit()


@pytest_asyncio.fixture
async def rice_in_march(energy_values, foods, db_establishment, make_user_with_role):
    """Two kilos of rice received in March 2026, which convert to grams."""
    _, responsible_id = await make_user_with_role(UserRole.FIELD_WORKER)
    await add_intake(
        db_establishment.id, responsible_id, MARCH_INTAKE, [(foods.rice, "2")]
    )
