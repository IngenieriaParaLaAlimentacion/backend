from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.food_catalog.nutrient import Nutrient


class NutrientRepository:
    """Persistence operations for Nutrient entities."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, nutrient: Nutrient) -> Nutrient:
        """Stage a new nutrient for insertion."""
        self.db.add(nutrient)
        return nutrient

    async def update(self, nutrient: Nutrient) -> Nutrient:
        """Persist changes made to an existing nutrient."""
        await self.db.flush()
        return nutrient

    async def get_all(self) -> list[Nutrient]:
        """Return every nutrient.

        Seed-only: loads the full table into memory to build the upsert-by-code
        diff at container boot. Do not call from request-time code — use a
        paginated listing method instead.
        """
        result = await self.db.execute(select(Nutrient))
        return list(result.scalars().all())
