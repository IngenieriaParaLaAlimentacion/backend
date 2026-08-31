from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.food_catalog.food import Food


class FoodRepository:
    """Persistence operations for Food entities."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, food: Food) -> Food:
        """Stage a new food for insertion."""
        self.db.add(food)
        return food

    async def update(self, food: Food) -> Food:
        """Persist changes made to an existing food."""
        await self.db.flush()
        return food

    async def get_all(self) -> list[Food]:
        """Return every food."""
        result = await self.db.execute(select(Food))
        return list(result.scalars().all())
