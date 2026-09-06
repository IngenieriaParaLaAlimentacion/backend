from sqlalchemy import asc, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.food_catalog import FoodSortOrder
from app.models.food_catalog.food_category import FoodCategory

# Maps each FoodSortOrder value to its SQLAlchemy order clause.
# KeyError on an unmapped value is intentional: it surfaces missing cases immediately.
_SORT_CLAUSES = {
    FoodSortOrder.NAME_ASC: asc(func.lower(FoodCategory.name)),
    FoodSortOrder.NAME_DESC: desc(func.lower(FoodCategory.name)),
}


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

    async def get_all(
        self, sort_order: FoodSortOrder = FoodSortOrder.NAME_ASC
    ) -> list[FoodCategory]:
        """Return every food category, sorted by ``sort_order``.

        Unlike ``foods``/``food_nutrient_values``, this table is structurally
        bounded to the ~26 SARA 2 food groups, so loading it whole is safe
        both for the seed script's upsert diff (where the order is irrelevant)
        and for request-time listing — no separate paginated/listing method
        is needed here.
        """
        result = await self.db.execute(
            select(FoodCategory).order_by(_SORT_CLAUSES[sort_order])
        )
        return list(result.scalars().all())
