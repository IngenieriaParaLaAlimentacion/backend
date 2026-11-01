from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.food_catalog.food import Food
from app.models.food_intakes.food_intake import FoodIntake
from app.models.food_intakes.food_intake_item import FoodIntakeItem
from app.utils.db import insert_with_savepoint


class FoodIntakeRepository:
    """Persistence operations for FoodIntake entities."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, intake: FoodIntake) -> FoodIntake:
        """Insert an intake together with its items.

        The insert cascades into ``food_intake_items``, so the primary key is
        named explicitly: a rejected item (unknown food, non-positive quantity)
        must not be reported as a duplicate intake.

        Raises:
            UniqueConstraintError: if ``intake.id`` is already taken. The caller
                re-queries to decide whether this is an offline replay.
        """
        return await insert_with_savepoint(
            self.db,
            intake,
            field="id",
            value=intake.id,
            constraint="food_intakes_pkey",
        )

    async def get_by_id(self, intake_id: UUID) -> FoodIntake | None:
        """Return an intake with its items, or None.

        Each item's ``food`` and that food's ``category`` are eager-loaded:
        items carry no unit of their own, so a caller reading the quantity's
        unit reads ``item.food.base_unit``.
        """
        result = await self.db.execute(
            select(FoodIntake)
            .where(FoodIntake.id == intake_id)
            .options(
                selectinload(FoodIntake.items)
                .selectinload(FoodIntakeItem.food)
                .selectinload(Food.category)
            )
        )
        return result.scalar_one_or_none()

    async def sum_quantities_by_food(
        self, establishment_id: UUID, start: datetime, end: datetime
    ) -> dict[UUID, Decimal]:
        """Return the total quantity received per food in ``[start, end)``.

        Quantities are summed in each food's ``base_unit``; a food with no
        intake in the window is absent from the mapping.
        """
        total = func.sum(FoodIntakeItem.quantity)
        result = await self.db.execute(
            select(FoodIntakeItem.food_id, total)
            .join(FoodIntake, FoodIntake.id == FoodIntakeItem.food_intake_id)
            .where(
                FoodIntake.establishment_id == establishment_id,
                FoodIntake.occurred_at >= start,
                FoodIntake.occurred_at < end,
            )
            .group_by(FoodIntakeItem.food_id)
        )
        return {food_id: quantity for food_id, quantity in result.all()}
