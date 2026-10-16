from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.food_catalog.gapa_food_category import GapaFoodCategory


class GapaFoodCategoryRepository:
    """Persistence operations for GapaFoodCategory entities."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, category: GapaFoodCategory) -> GapaFoodCategory:
        """Stage a new GAPA food group for insertion."""
        self.db.add(category)
        return category

    async def update(self, category: GapaFoodCategory) -> GapaFoodCategory:
        """Persist changes made to an existing GAPA food group."""
        await self.db.flush()
        return category

    async def get_all(self) -> list[GapaFoodCategory]:
        """Return every GAPA food group, ordered by code.

        The table holds the six GAPA groups, so loading it whole is safe.
        """
        result = await self.db.execute(
            select(GapaFoodCategory).order_by(GapaFoodCategory.code)
        )
        return list(result.scalars().all())
