from __future__ import annotations

from sqlalchemy import asc, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain.food_catalog import FoodListingParams, FoodSortOrder
from app.models.food_catalog.food import Food
from app.utils.db import execute_paginated, ilike_condition

# Maps each FoodSortOrder value to its SQLAlchemy order clause.
# KeyError on an unmapped value is intentional: it surfaces missing cases immediately.
_SORT_CLAUSES = {
    FoodSortOrder.NAME_ASC: asc(func.lower(Food.name)),
    FoodSortOrder.NAME_DESC: desc(func.lower(Food.name)),
}


class FoodRepository:
    """Persistence operations for Food entities."""

    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def _listing_conditions(params: FoodListingParams) -> list:
        """Build the filter conditions for a food catalog listing."""
        conditions = []
        if params.search:
            conditions.append(ilike_condition(Food.name, params.search))
        if params.category_id is not None:
            conditions.append(Food.category_id == params.category_id)
        if params.is_active is not None:
            conditions.append(Food.is_active == params.is_active)
        return conditions

    async def create(self, food: Food) -> Food:
        """Stage a new food for insertion."""
        self.db.add(food)
        return food

    async def update(self, food: Food) -> Food:
        """Persist changes made to an existing food."""
        await self.db.flush()
        return food

    async def list(
        self,
        limit: int,
        offset: int,
        params: FoodListingParams,
    ) -> tuple[list[Food], int]:
        """Return a paginated list of foods and the total matching count.

        ``category`` is eager-loaded via ``selectinload`` so the listing view
        can read the category ref without a per-row lookup.
        """
        base_query = select(Food).options(selectinload(Food.category))
        count_query = select(func.count()).select_from(Food)
        foods, total = await execute_paginated(
            self.db,
            base_query,
            count_query,
            _SORT_CLAUSES[params.sort_order],
            limit,
            offset,
            conditions=self._listing_conditions(params),
        )
        return foods, total

    async def get_all(self) -> list[Food]:
        """Return every food.

        Seed-only: loads the full table into memory to build the upsert-by-code
        diff at container boot. Do not call from request-time code — use a
        paginated listing method instead.
        """
        result = await self.db.execute(select(Food))
        return list(result.scalars().all())
