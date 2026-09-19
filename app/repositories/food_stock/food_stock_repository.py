from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable, Collection
from decimal import Decimal
from typing import ClassVar
from uuid import UUID

from sqlalchemy import (
    Numeric,
    Row,
    Select,
    Subquery,
    asc,
    column,
    delete,
    desc,
    func,
    literal,
    select,
    union_all,
    update,
    values,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain.food_stock import (
    FoodMovementDirection,
    FoodMovementDomain,
    FoodMovementListingParams,
    FoodStockListingParams,
    FoodStockSortOrder,
)
from app.models.food_catalog.food import Food
from app.models.food_intakes.food_intake import FoodIntake
from app.models.food_intakes.food_intake_item import FoodIntakeItem
from app.models.food_outflows.food_outflow import FoodOutflow
from app.models.food_outflows.food_outflow_item import FoodOutflowItem
from app.models.food_stock.food_stock import FoodStock
from app.utils.db import (
    execute_count,
    execute_paginated,
    execute_paginated_rows,
    stream_all,
)

# A KeyError on an unmapped value is intentional: it surfaces a missing case
# immediately rather than silently falling back to an arbitrary order.
#
# Each pairs the sort column with `id` as a tiebreaker: every criterion here
# ties in normal operation -- depleted foods all sit at 0.000, and one batched
# intake stamps the same updated_at on every row it touched -- and an
# unresolved tie lets LIMIT/OFFSET repeat a row on one page and skip another.
_SORT_CLAUSES = {
    FoodStockSortOrder.NAME_ASC: (asc(func.lower(Food.name)), asc(FoodStock.id)),
    FoodStockSortOrder.NAME_DESC: (desc(func.lower(Food.name)), asc(FoodStock.id)),
    FoodStockSortOrder.QUANTITY_DESC: (desc(FoodStock.quantity), asc(FoodStock.id)),
    FoodStockSortOrder.QUANTITY_ASC: (asc(FoodStock.quantity), asc(FoodStock.id)),
    FoodStockSortOrder.UPDATED_AT_DESC: (
        desc(FoodStock.updated_at),
        asc(FoodStock.id),
    ),
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
        """Add each food's quantity to its balance, creating rows on first arrival."""
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

    async def decrease_many(
        self, establishment_id: UUID, quantities: dict[UUID, Decimal]
    ) -> set[UUID]:
        """Subtract each food's quantity, returning the foods the balance covered.

        The ``quantity >= requested`` guard stays inside the UPDATE, so checking
        a balance and spending it remain one act and two concurrent outflows
        cannot both pass a balance that only covers one. The foods missing from
        the result are the ones that fell short — either not enough held, or no
        row at all — and the caller decides what that means.

        ``quantities`` must already be aggregated per food: two rows for the
        same food would join the same balance twice and only one would apply.
        """
        if not quantities:
            return set()

        requested = values(
            column("food_id", PGUUID(as_uuid=True)),
            column("quantity", Numeric(10, 3)),
            name="requested",
        ).data(sorted(quantities.items()))
        result = await self.db.execute(
            update(FoodStock)
            .where(
                FoodStock.establishment_id == establishment_id,
                FoodStock.food_id == requested.c.food_id,
                FoodStock.quantity >= requested.c.quantity,
            )
            .values(
                quantity=FoodStock.quantity - requested.c.quantity,
                updated_at=func.now(),
            )
            .returning(FoodStock.food_id)
        )
        return set(result.scalars())

    async def get_many(
        self, establishment_id: UUID, food_ids: Collection[UUID]
    ) -> dict[UUID, Decimal]:
        """Return the balances held for these foods.

        A food the establishment never received has no row and is simply absent
        from the mapping, which is not the same fact as a balance of zero.
        """
        if not food_ids:
            return {}

        result = await self.db.execute(
            select(FoodStock.food_id, FoodStock.quantity).where(
                FoodStock.establishment_id == establishment_id,
                FoodStock.food_id.in_(food_ids),
            )
        )
        return dict(result.all())

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

    # Per direction: the header table, its event-date column, and the domain
    # builder for a hydrated header.
    #
    # No fallback entry on purpose: `_build_movements_subquery` iterates the
    # enum and looks each member up here, so a direction added to the enum but
    # forgotten here raises a KeyError instead of silently vanishing from the
    # unfiltered listing.
    _MOVEMENT_SOURCES: ClassVar[
        dict[FoodMovementDirection, tuple[type, object, Callable[[object], object]]]
    ] = {
        FoodMovementDirection.IN: (
            FoodIntake,
            FoodIntake.occurred_at,
            FoodMovementDomain.from_intake,
        ),
        FoodMovementDirection.OUT: (
            FoodOutflow,
            FoodOutflow.occurred_at,
            FoodMovementDomain.from_outflow,
        ),
    }

    def _movement_branch(
        self,
        direction: FoodMovementDirection,
        establishment_id: UUID,
        params: FoodMovementListingParams,
    ) -> Select:
        """Build one header branch of the movements union.

        Both filters go inside the branch, not on the union: the establishment
        column does not survive into the union's shape, and keeping the date
        bounds on each table's own column is what lets each branch use its
        ``(establishment_id, event date)`` index.
        """
        model, event_at, _ = self._MOVEMENT_SOURCES[direction]
        conditions = [model.establishment_id == establishment_id]
        if params.occurred_from is not None:
            conditions.append(event_at >= params.occurred_from)
        if params.occurred_to is not None:
            conditions.append(event_at <= params.occurred_to)
        return select(
            model.id.label("id"),
            literal(direction.value).label("direction"),
            event_at.label("occurred_at"),
        ).where(*conditions)

    def _build_movements_subquery(
        self, establishment_id: UUID, params: FoodMovementListingParams
    ) -> Subquery:
        """Build the id/direction/occurred_at UNION ALL of the header tables.

        Only the three columns the ordering needs cross the union; everything
        else is hydrated per direction afterwards. ``source`` in particular
        cannot cross it -- the two tables carry distinct Postgres enum types,
        and unioning those fails at query time, not at import time.

        Iteration is over ``FoodMovementDirection``, so branch order is
        deterministic regardless of the request. A direction filter drops the
        other branch entirely rather than filtering the union after the fact.
        """
        requested = (
            {params.direction} if params.direction else set(FoodMovementDirection)
        )
        branches = [
            self._movement_branch(direction, establishment_id, params)
            for direction in FoodMovementDirection
            if direction in requested
        ]
        return union_all(*branches).subquery()

    async def _get_intakes_by_id(
        self, intake_ids: list[UUID]
    ) -> dict[UUID, FoodIntake]:
        if not intake_ids:
            return {}
        result = await self.db.execute(
            select(FoodIntake)
            .options(
                selectinload(FoodIntake.responsible),
                selectinload(FoodIntake.items).selectinload(FoodIntakeItem.food),
            )
            .where(FoodIntake.id.in_(intake_ids))
        )
        return {intake.id: intake for intake in result.scalars().all()}

    async def _get_outflows_by_id(
        self, outflow_ids: list[UUID]
    ) -> dict[UUID, FoodOutflow]:
        if not outflow_ids:
            return {}
        result = await self.db.execute(
            select(FoodOutflow)
            .options(
                selectinload(FoodOutflow.responsible),
                selectinload(FoodOutflow.items).selectinload(FoodOutflowItem.food),
            )
            .where(FoodOutflow.id.in_(outflow_ids))
        )
        return {outflow.id: outflow for outflow in result.scalars().all()}

    @staticmethod
    def _ids_of(page_rows: list[Row], direction: FoodMovementDirection) -> list[UUID]:
        """Return the ids in the page that belong to one direction."""
        return [row.id for row in page_rows if row.direction == direction]

    async def _hydrate_page_rows(
        self, page_rows: list[Row]
    ) -> dict[FoodMovementDirection, dict[UUID, object]]:
        """Fetch the full header for every id in the page, keyed by direction.

        Each fetch short-circuits to ``{}`` when the page carries no row of that
        direction, so a single-direction page costs one hydration, not two.
        """
        return {
            FoodMovementDirection.IN: await self._get_intakes_by_id(
                self._ids_of(page_rows, FoodMovementDirection.IN)
            ),
            FoodMovementDirection.OUT: await self._get_outflows_by_id(
                self._ids_of(page_rows, FoodMovementDirection.OUT)
            ),
        }

    def _assemble_movements(
        self,
        page_rows: list[Row],
        hydrated: dict[FoodMovementDirection, dict[UUID, object]],
    ) -> list[FoodMovementDomain]:
        """Rebuild domain movements in the page's original (already sorted) order."""
        movements = []
        for row in page_rows:
            direction = FoodMovementDirection(row.direction)
            _, _, build = self._MOVEMENT_SOURCES[direction]
            movements.append(build(hydrated[direction][row.id]))
        return movements

    async def list_movements(
        self,
        establishment_id: UUID,
        limit: int,
        offset: int,
        params: FoodMovementListingParams,
    ) -> tuple[list[FoodMovementDomain], int]:
        """Return a page of the establishment's movement documents, newest first.

        One row per document -- both directions merged into one sequence, each
        tagged with its own -- rather than one row per food line.

        Unlike its neighbours this returns domain objects rather than ORM rows:
        the reassembly interleaves two ORM types in the order of raw rows
        carrying the union's column names, and handing that to the service would
        force it to know the union's shape.

        ``total`` and the page slice read the same subquery object, so they
        cannot disagree about the filter.

        ``id DESC`` breaks ties on ``occurred_at`` deterministically -- a batch
        of movements sharing one timestamp is the normal case here, and an
        unresolved tie lets LIMIT/OFFSET repeat a row on one page and skip
        another.
        """
        movements = self._build_movements_subquery(establishment_id, params)

        page_rows, total = await execute_paginated_rows(
            self.db,
            select(movements.c.id, movements.c.direction, movements.c.occurred_at),
            select(func.count()).select_from(movements),
            (movements.c.occurred_at.desc(), movements.c.id.desc()),
            limit,
            offset,
        )

        hydrated = await self._hydrate_page_rows(page_rows)
        return self._assemble_movements(page_rows, hydrated), total
