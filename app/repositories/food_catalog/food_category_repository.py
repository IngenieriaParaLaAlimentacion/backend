from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.food_catalog.food_category import FoodCategory


class FoodCategoryRepository:
    """Persistence operations for FoodCategory entities."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, category: FoodCategory) -> FoodCategory:
        """Stage a new food category for insertion."""
        self.db.add(category)
        return category

    async def update(self, category: FoodCategory) -> FoodCategory:
        """Persist changes made to an existing food category."""
        await self.db.flush()
        return category

    async def get_all(self) -> list[FoodCategory]:
        """Return every food category.

        Seed-only: loads the full table into memory to build the upsert-by-code
        diff at container boot. Do not call from request-time code — use a
        paginated listing method instead.
        """
        result = await self.db.execute(select(FoodCategory))
        return list(result.scalars().all())
