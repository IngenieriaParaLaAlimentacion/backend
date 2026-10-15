from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from app.domain.common_domains import IdentifierRefDomain
from app.domain.food_catalog import MeasurementUnit
from app.domain.food_intake import FoodIntakeOriginType, FoodLineDomain
from app.domain.food_outflow import FoodOutflowCategory
from app.domain.measurement import ResponsibleRefDomain


class FoodStockSortOrder(StrEnum):
    """Sort orders accepted by the establishment stock listing."""

    NAME_ASC = "name_asc"
    NAME_DESC = "name_desc"
    QUANTITY_DESC = "quantity_desc"
    QUANTITY_ASC = "quantity_asc"
    UPDATED_AT_DESC = "updated_at_desc"


class FoodMovementDirection(StrEnum):
    """Which way a movement moved the balance."""

    IN = "in"
    OUT = "out"


@dataclass
class FoodStockListingParams:
    """Query parameters for an establishment's stock listing."""

    category_id: UUID | None = None
    only_available: bool = False
    sort_order: FoodStockSortOrder = FoodStockSortOrder.NAME_ASC


@dataclass
class FoodMovementListingParams:
    """Query parameters for an establishment's movement listing."""

    direction: FoodMovementDirection | None = None
    occurred_from: datetime | None = None
    occurred_to: datetime | None = None
    food_id: UUID | None = None


@dataclass
class FoodStockItemDomain:
    """How much of one food an establishment holds right now."""

    food: IdentifierRefDomain
    category: IdentifierRefDomain
    unit: MeasurementUnit
    quantity: Decimal
    updated_at: datetime

    @classmethod
    def from_db(cls, stock) -> "FoodStockItemDomain":
        """Build from a stock row with ``food`` and its ``category`` loaded."""
        return cls(
            food=IdentifierRefDomain.from_db(stock.food),
            category=IdentifierRefDomain.from_db(stock.food.category),
            unit=stock.food.base_unit,
            quantity=stock.quantity,
            updated_at=stock.updated_at,
        )


@dataclass
class FoodMovementSummaryDomain:
    """One row of the movement listing: a movement without its lines.

    ``food_count`` is how many *distinct* foods the movement touched.
    """

    id: UUID
    direction: FoodMovementDirection
    occurred_at: datetime
    responsible: ResponsibleRefDomain
    food_count: int
    origin_type: FoodIntakeOriginType | None
    is_recurring: bool | None
    category: FoodOutflowCategory | None

    @classmethod
    def from_rows(cls, page_row, summary_row) -> "FoodMovementSummaryDomain":
        """Build from the union's page row plus its per-direction summary row."""
        return cls(
            id=page_row.id,
            direction=FoodMovementDirection(page_row.direction),
            occurred_at=page_row.occurred_at,
            responsible=ResponsibleRefDomain(
                id=summary_row.responsible_id,
                name=summary_row.responsible_name,
                last_name=summary_row.responsible_last_name,
            ),
            food_count=summary_row.food_count,
            origin_type=getattr(summary_row, "origin_type", None),
            is_recurring=getattr(summary_row, "is_recurring", None),
            category=summary_row.category,
        )


@dataclass
class FoodMovementDetailDomain:
    """One movement -- an intake or an outflow -- with all of its lines.

    ``source`` is annotated ``str`` because the attribute carries a
    ``FoodIntakeSource`` *or* a ``FoodOutflowSource``.

    ``items`` are rendered as stored, repeated foods included.
    """

    id: UUID
    direction: FoodMovementDirection
    occurred_at: datetime
    comments: str | None
    source: str
    origin_type: FoodIntakeOriginType | None
    is_recurring: bool | None
    responsible: ResponsibleRefDomain
    items: list[FoodLineDomain]
    category: FoodOutflowCategory | None

    @classmethod
    def from_db(
        cls, movement, direction: FoodMovementDirection
    ) -> "FoodMovementDetailDomain":
        """Build from an intake or outflow row with ``responsible`` and ``items``
        (each with its ``food``) loaded."""
        return cls(
            id=movement.id,
            direction=direction,
            occurred_at=movement.occurred_at,
            comments=movement.comments,
            source=movement.source,
            origin_type=(
                movement.origin_type if direction == FoodMovementDirection.IN else None
            ),
            is_recurring=(
                movement.is_recurring if direction == FoodMovementDirection.IN else None
            ),
            responsible=ResponsibleRefDomain.from_db(movement.responsible),
            items=[FoodLineDomain.from_db(item) for item in movement.items],
            category=(
                movement.category if direction == FoodMovementDirection.OUT else None
            ),
        )
