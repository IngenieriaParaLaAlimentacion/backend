from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Collection
from decimal import Decimal
from typing import ClassVar, NamedTuple
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
    distinct,
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
from sqlalchemy.orm import InstrumentedAttribute, joinedload, selectinload

from app.domain.food_stock import (
    FoodMovementDetailDomain,
    FoodMovementDirection,
    FoodMovementListingParams,
    FoodMovementSummaryDomain,
    FoodStockListingParams,
    FoodStockSortOrder,
)
from app.models.auth.user import User
from app.models.food_catalog.food import Food
from app.models.food_catalog.food_nutrient_value import FoodNutrientValue
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


class _MovementSource(NamedTuple):
    """The header table, its event-date column and its line table."""

    model: type
    occurred_at: InstrumentedAttribute
    item_model: type
    item_fk: InstrumentedAttribute


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

    # Per direction: the header table, its event-date column, and the line
    # table with the foreign key back to the header. No fallback entry: a
    # direction missing here raises a KeyError instead of vanishing silently.
    _MOVEMENT_SOURCES: ClassVar[dict[FoodMovementDirection, _MovementSource]] = {
        FoodMovementDirection.IN: _MovementSource(
            FoodIntake,
            FoodIntake.occurred_at,
            FoodIntakeItem,
            FoodIntakeItem.food_intake_id,
        ),
        FoodMovementDirection.OUT: _MovementSource(
            FoodOutflow,
            FoodOutflow.occurred_at,
            FoodOutflowItem,
            FoodOutflowItem.food_outflow_id,
        ),
    }

    def _movement_branch(
        self,
        direction: FoodMovementDirection,
        establishment_id: UUID,
        params: FoodMovementListingParams,
    ) -> Select:
        """Select id, direction and occurred_at for one direction's movements."""
        source = self._MOVEMENT_SOURCES[direction]
        # Filters belong in the branch: establishment_id does not cross the
        # union, and per-table dates keep the (establishment_id, date) index.
        conditions = [source.model.establishment_id == establishment_id]
        if params.occurred_from is not None:
            conditions.append(source.occurred_at >= params.occurred_from)
        if params.occurred_to is not None:
            conditions.append(source.occurred_at <= params.occurred_to)
        if params.food_id is not None:
            # EXISTS, not a join: a movement listing the same food twice would
            # come back twice, and be counted twice in the total.
            conditions.append(
                select(1)
                .where(
                    source.item_fk == source.model.id,
                    source.item_model.food_id == params.food_id,
                )
                .exists()
            )
        return select(
            source.model.id.label("id"),
            literal(direction.value).label("direction"),
            source.occurred_at.label("occurred_at"),
        ).where(*conditions)

    def _build_movements_subquery(
        self, establishment_id: UUID, params: FoodMovementListingParams
    ) -> Subquery:
        """UNION ALL the header tables into id/direction/occurred_at rows."""
        requested = (
            {params.direction} if params.direction else set(FoodMovementDirection)
        )
        # Iterate the enum, not `requested`, so branch order never depends on
        # the request. Do not widen these columns: the two tables' `source` are
        # distinct Postgres enum types and unioning them fails at query time.
        branches = [
            self._movement_branch(direction, establishment_id, params)
            for direction in FoodMovementDirection
            if direction in requested
        ]
        return union_all(*branches).subquery()

    async def _summaries_by_id(
        self, direction: FoodMovementDirection, movement_ids: list[UUID]
    ) -> dict[UUID, Row]:
        """Fetch responsible, food count, and direction-specific facts."""
        if not movement_ids:
            return {}
        source = self._MOVEMENT_SOURCES[direction]
        origin_type = (
            FoodIntake.origin_type
            if direction == FoodMovementDirection.IN
            else literal(None)
        )
        is_recurring = (
            FoodIntake.is_recurring
            if direction == FoodMovementDirection.IN
            else literal(None)
        )
        category = (
            source.model.category
            if direction == FoodMovementDirection.OUT
            else literal(None, type_=source.model.comments.type)
        )
        result = await self.db.execute(
            select(
                source.model.id.label("id"),
                User.id.label("responsible_id"),
                User.name.label("responsible_name"),
                User.last_name.label("responsible_last_name"),
                category.label("category"),
                func.count(distinct(source.item_model.food_id)).label("food_count"),
                origin_type.label("origin_type"),
                is_recurring.label("is_recurring"),
            )
            .join(User, User.id == source.model.responsible_id)
            # Outer: a movement with no lines counts 0 instead of vanishing.
            .outerjoin(source.item_model, source.item_fk == source.model.id)
            .where(source.model.id.in_(movement_ids))
            .group_by(source.model.id, User.id)
        )
        return {row.id: row for row in result.all()}

    @staticmethod
    def _ids_of(page_rows: list[Row], direction: FoodMovementDirection) -> list[UUID]:
        """Return the ids in the page that belong to one direction."""
        return [row.id for row in page_rows if row.direction == direction]

    async def _summarize_page_rows(
        self, page_rows: list[Row]
    ) -> dict[FoodMovementDirection, dict[UUID, Row]]:
        """Fetch the listing fields for every id in the page, keyed by direction."""
        return {
            direction: await self._summaries_by_id(
                direction, self._ids_of(page_rows, direction)
            )
            for direction in FoodMovementDirection
        }

    @staticmethod
    def _assemble_summaries(
        page_rows: list[Row],
        summaries: dict[FoodMovementDirection, dict[UUID, Row]],
    ) -> list[FoodMovementSummaryDomain]:
        """Rebuild domain rows in the page's original (already sorted) order."""
        return [
            FoodMovementSummaryDomain.from_rows(
                row, summaries[FoodMovementDirection(row.direction)][row.id]
            )
            for row in page_rows
        ]

    async def list_movements(
        self,
        establishment_id: UUID,
        limit: int,
        offset: int,
        params: FoodMovementListingParams,
    ) -> tuple[list[FoodMovementSummaryDomain], int]:
        """Return a page of the establishment's movements and the total count.

        Intakes and outflows merged into one sequence, one row per movement,
        each tagged with its direction and carrying its responsible and how
        many distinct foods it touched -- not its lines. Ordered by
        ``occurred_at`` descending, ties broken by ``id`` descending.
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

        summaries = await self._summarize_page_rows(page_rows)
        return self._assemble_summaries(page_rows, summaries), total

    async def get_movement(
        self, establishment_id: UUID, movement_id: UUID
    ) -> FoodMovementDetailDomain | None:
        """Return one of the establishment's movements with its lines, or None.

        Probes each direction in turn, since the id alone does not say which
        table holds it.
        """
        for direction in FoodMovementDirection:
            source = self._MOVEMENT_SOURCES[direction]
            result = await self.db.execute(
                select(source.model)
                .options(
                    joinedload(source.model.responsible),
                    selectinload(source.model.items).selectinload(
                        source.item_model.food
                    ),
                )
                # Scoping in the WHERE, not in a later comparison: a movement of
                # another establishment is not found rather than found and hidden.
                .where(
                    source.model.id == movement_id,
                    source.model.establishment_id == establishment_id,
                )
            )
            movement = result.unique().scalar_one_or_none()
            if movement is not None:
                return FoodMovementDetailDomain.from_db(movement, direction)
        return None

    async def stocked_foods(self, establishment_id: UUID) -> list[tuple[Food, Decimal]]:
        """Return positive balances with nutrient and GAPA data loaded."""
        result = await self.db.execute(
            select(Food, FoodStock.quantity)
            .join(FoodStock, FoodStock.food_id == Food.id)
            .where(
                FoodStock.establishment_id == establishment_id, FoodStock.quantity > 0
            )
            .options(
                selectinload(Food.gapa_category),
                selectinload(Food.nutrient_values).selectinload(
                    FoodNutrientValue.nutrient
                ),
            )
            .order_by(Food.id)
        )
        return list(result.all())
