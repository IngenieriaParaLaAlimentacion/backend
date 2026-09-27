import pytest_asyncio

from tests.integration.food.stock.helpers import (
    Foods,
)


@pytest_asyncio.fixture
async def foods(app) -> Foods:
    """Seed two catalog foods with different base units."""
    from app.db.database import AsyncSessionLocal
    from app.domain.food_catalog import MeasurementUnit
    from app.models.food_catalog.food import Food
    from app.models.food_catalog.food_category import FoodCategory

    async with AsyncSessionLocal() as session:
        cereals = FoodCategory(code="cereales", name="Cereales")
        session.add(cereals)
        await session.flush()

        rice = Food(
            code="arroz",
            name="Arroz",
            category_id=cereals.id,
            base_unit=MeasurementUnit.KILOGRAMOS,
        )
        eggs = Food(
            code="huevo",
            name="Huevo",
            category_id=cereals.id,
            base_unit=MeasurementUnit.UNIDADES,
        )
        session.add_all([rice, eggs])
        await session.commit()
        return Foods(rice=rice.id, eggs=eggs.id)
