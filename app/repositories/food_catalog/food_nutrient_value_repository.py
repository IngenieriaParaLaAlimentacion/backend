from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.food_catalog.food_nutrient_value import FoodNutrientValue


class FoodNutrientValueRepository:
    """Persistence operations for FoodNutrientValue entities."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, value: FoodNutrientValue) -> FoodNutrientValue:
        """Stage a new food-nutrient reading for insertion."""
        self.db.add(value)
        return value

    async def update(self, value: FoodNutrientValue) -> FoodNutrientValue:
        """Persist changes made to an existing food-nutrient reading."""
        await self.db.flush()
        return value

    async def get_all(self) -> list[FoodNutrientValue]:
        """Return every stored food-nutrient reading.

        Seed-only: loads the full table into memory to build the upsert-by-
        (food_id, nutrient_id) diff at container boot. Do not call from
        request-time code — use a paginated listing method instead.
        """
        result = await self.db.execute(select(FoodNutrientValue))
        return list(result.scalars().all())
