from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Row, asc, delete, desc, func, literal, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain.food_stock import (
    FoodMovementDirection,
    FoodStockListingParams,
    FoodStockSortOrder,
)
from app.models.food_catalog.food import Food
from app.models.food_intakes.food_intake import FoodIntake
from app.models.food_intakes.food_intake_item import FoodIntakeItem
from app.models.food_outflows.food_outflow import FoodOutflow
from app.models.food_outflows.food_outflow_item import FoodOutflowItem
from app.models.food_stock.food_stock import FoodStock
from app.utils.db import execute_count, execute_paginated, stream_all

# A KeyError on an unmapped value is intentional: it surfaces a missing case
# immediately rather than silently falling back to an arbitrary order.
_SORT_CLAUSES = {
    FoodStockSortOrder.NAME_ASC: asc(func.lower(Food.name)),
    FoodStockSortOrder.NAME_DESC: desc(func.lower(Food.name)),
    FoodStockSortOrder.QUANTITY_DESC: desc(FoodStock.quantity),
    FoodStockSortOrder.QUANTITY_ASC: asc(FoodStock.quantity),
    FoodStockSortOrder.UPDATED_AT_DESC: desc(FoodStock.updated_at),
}

_CONFLICT_TARGET = ["establishment_id", "food_id"]


class FoodStockRepository:
    """Reads and moves the materialized per-establishment food balance.

    Both movement methods are single statements on purpose. Reading a balance
    and then writing it back would let two concurrent movements interleave and
    lose one of them; letting Postgres do the arithmetic in place cannot.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def increase_batch(
        self, establishment_id: UUID, quantities: dict[UUID, Decimal]
    ) -> None:
        """Add each food's quantity to its balance, creating rows on first arrival.
        """
        if not quantities:
            return

        stmt = insert(FoodStock).values(
            [
                {
                    "id": uuid.uuid4(),
                    "establishment_id": establishment_id,
                    "food_id": food_id,
                    "quantity": quantity,
                }
                for food_id, quantity in sorted(quantities.items())
            ]
        )
        await self.db.execute(
            stmt.on_conflict_do_update(
                index_elements=_CONFLICT_TARGET,
                set_={
                    "quantity": FoodStock.quantity + stmt.excluded.quantity,
                    "updated_at": func.now(),
                },
            )
        )

    async def decrease(
        self, establishment_id: UUID, food_id: UUID, quantity: Decimal
    ) -> bool:
        """Subtract ``quantity``, and report whether the balance allowed it.

        The ``quantity >= :quantity`` guard makes checking the balance and
        spending it the same act, so two concurrent outflows cannot both pass a
        balance that only covers one. Returns False when the establishment has
        no row for this food at all, or not enough of it — the caller decides
        what that means.
        """
        result = await self.db.execute(
            update(FoodStock)
            .where(
                FoodStock.establishment_id == establishment_id,
                FoodStock.food_id == food_id,
                FoodStock.quantity >= quantity,
            )
            .values(quantity=FoodStock.quantity - quantity, updated_at=func.now())
        )
        return result.rowcount == 1

    async def get(self, establishment_id: UUID, food_id: UUID) -> FoodStock | None:
        """Return the balance row for one food, or None if there never was one."""
        result = await self.db.execute(
            select(FoodStock).where(
                FoodStock.establishment_id == establishment_id,
                FoodStock.food_id == food_id,
            )
        )
        return result.scalar_one_or_none()

    async def recompute(self, establishment_id: UUID) -> None:
        """Rebuild the establishment's balances from its movements.

        The repair path a materialized balance has to have: it recovers from
        any drift by replacing every row with the sum of what actually moved.
        Foods whose movements cancel out keep a zero row, matching what the
        incremental path leaves behind.
        """
        totals: dict[UUID, Decimal] = {}
        for model, item_model, join_column, sign in (
            (FoodIntake, FoodIntakeItem, FoodIntakeItem.food_intake_id, 1),
            (FoodOutflow, FoodOutflowItem, FoodOutflowItem.food_outflow_id, -1),
        ):
            rows = await self.db.execute(
                select(item_model.food_id, func.sum(item_model.quantity))
                .join(model, model.id == join_column)
                .where(model.establishment_id == establishment_id)
                .group_by(item_model.food_id)
            )
            for food_id, total in rows.all():
                totals[food_id] = totals.get(food_id, Decimal(0)) + sign * total

        await self.db.execute(
            delete(FoodStock).where(FoodStock.establishment_id == establishment_id)
        )
        if totals:
            self.db.add_all(
                [
                    FoodStock(
                        establishment_id=establishment_id,
                        food_id=food_id,
                        quantity=quantity,
                    )
                    for food_id, quantity in totals.items()
                ]
            )
        await self.db.flush()

    @staticmethod
    def _listing_conditions(
        establishment_id: UUID, params: FoodStockListingParams
    ) -> list:
        """Build the filter conditions for an establishment's stock listing."""
        conditions = [FoodStock.establishment_id == establishment_id]
        if params.category_id is not None:
            conditions.append(Food.category_id == params.category_id)
        if params.only_available:
            conditions.append(FoodStock.quantity > 0)
        return conditions

    @staticmethod
    def _listing_queries() -> tuple:
        """Base and count queries for a stock listing.

        Both join ``foods`` because the listing sorts by food name and can
        filter by category, and the count has to see the same rows the page
        does.
        """
        base_query = (
            select(FoodStock)
            .join(Food, FoodStock.food_id == Food.id)
            .options(selectinload(FoodStock.food).selectinload(Food.category))
        )
        count_query = (
            select(func.count())
            .select_from(FoodStock)
            .join(Food, FoodStock.food_id == Food.id)
        )
        return base_query, count_query

    async def list_by_establishment(
        self,
        establishment_id: UUID,
        limit: int,
        offset: int,
        params: FoodStockListingParams,
    ) -> tuple[list[FoodStock], int]:
        """Return a page of the establishment's balances and the total count."""
        base_query, count_query = self._listing_queries()
        return await execute_paginated(
            self.db,
            base_query,
            count_query,
            _SORT_CLAUSES[params.sort_order],
            limit,
            offset,
            conditions=self._listing_conditions(establishment_id, params),
        )

    def stream_for_export(
        self, establishment_id: UUID, params: FoodStockListingParams
    ) -> AsyncIterator[FoodStock]:
        """Yield every balance matching ``params``, a chunk at a time.

        The caller's transaction must stay open for the whole iteration.
        """
        base_query, _ = self._listing_queries()
        return stream_all(
            self.db,
            base_query,
            _SORT_CLAUSES[params.sort_order],
            conditions=self._listing_conditions(establishment_id, params),
        )

    async def count_for_export(
        self, establishment_id: UUID, params: FoodStockListingParams
    ) -> int:
        """Size an export up front, so a client can detect a truncated file."""
        _, count_query = self._listing_queries()
        return await execute_count(
            self.db,
            count_query,
            conditions=self._listing_conditions(establishment_id, params),
        )

    def _movements_query(self, establishment_id: UUID, food_id: UUID):
        """Union of the intake and outflow lines touching one food.

        The two sides carry different column names for the same facts, so each
        is relabelled to a common shape and tagged with its direction — the
        balance's history is one sequence, not two lists the client must merge.
        """
        intakes = (
            select(
                FoodIntakeItem.id.label("id"),
                literal(FoodMovementDirection.IN.value).label("direction"),
                FoodIntake.received_at.label("occurred_at"),
                FoodIntakeItem.quantity.label("quantity"),
                FoodIntake.comments.label("comments"),
            )
            .join(FoodIntake, FoodIntake.id == FoodIntakeItem.food_intake_id)
            .where(
                FoodIntake.establishment_id == establishment_id,
                FoodIntakeItem.food_id == food_id,
            )
        )
        outflows = (
            select(
                FoodOutflowItem.id.label("id"),
                literal(FoodMovementDirection.OUT.value).label("direction"),
                FoodOutflow.occurred_at.label("occurred_at"),
                FoodOutflowItem.quantity.label("quantity"),
                FoodOutflow.comments.label("comments"),
            )
            .join(FoodOutflow, FoodOutflow.id == FoodOutflowItem.food_outflow_id)
            .where(
                FoodOutflow.establishment_id == establishment_id,
                FoodOutflowItem.food_id == food_id,
            )
        )
        return intakes.union_all(outflows).subquery()

    async def get_movements(
        self, establishment_id: UUID, food_id: UUID, limit: int, offset: int
    ) -> tuple[list[Row], int]:
        """Return a page of one food's movement history, newest first."""
        movements = self._movements_query(establishment_id, food_id)
        total = (
            await self.db.execute(select(func.count()).select_from(movements))
        ).scalar_one()
        rows = await self.db.execute(
            select(movements)
            .order_by(desc(movements.c.occurred_at), desc(movements.c.id))
            .limit(limit)
            .offset(offset)
        )
        return list(rows.all()), total
