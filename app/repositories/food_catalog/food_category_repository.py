from sqlalchemy import asc, select
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
        """Return every food category, ordered by its SARA 2 group number.

        Unlike ``foods``/``food_nutrient_values``, this table is structurally
        bounded to the ~26 SARA 2 food groups, so loading it whole is safe
        both for the seed script's upsert diff and for request-time listing —
        no separate paginated/listing method is needed here.
        """
        result = await self.db.execute(
            select(FoodCategory).order_by(asc(FoodCategory.sara2_group_number))
        )
        return list(result.scalars().all())
