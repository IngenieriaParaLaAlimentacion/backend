from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.food_catalog.food import Food
from app.models.food_outflows.food_outflow import FoodOutflow
from app.models.food_outflows.food_outflow_item import FoodOutflowItem
from app.utils.db import insert_with_savepoint


class FoodOutflowRepository:
    """Persistence operations for FoodOutflow entities."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, outflow: FoodOutflow) -> FoodOutflow:
        """Insert an outflow together with its items.

        The insert cascades into ``food_outflow_items``, so the primary key is
        named explicitly: a rejected item (unknown food, non-positive quantity)
        must not be reported as a duplicate outflow.

        Raises:
            UniqueConstraintError: if ``outflow.id`` is already taken. The
                caller re-queries to decide whether this is an offline replay.
        """
        return await insert_with_savepoint(
            self.db,
            outflow,
            field="id",
            value=outflow.id,
            constraint="food_outflows_pkey",
        )

    async def get_by_id(self, outflow_id: UUID) -> FoodOutflow | None:
        """Return an outflow with its items, or None.

        Each item's ``food`` and that food's ``category`` are eager-loaded:
        items carry no unit of their own, so a caller reading the quantity's
        unit reads ``item.food.base_unit``.
        """
        result = await self.db.execute(
            select(FoodOutflow)
            .where(FoodOutflow.id == outflow_id)
            .options(
                selectinload(FoodOutflow.items)
                .selectinload(FoodOutflowItem.food)
                .selectinload(Food.category)
            )
        )
        return result.scalar_one_or_none()
