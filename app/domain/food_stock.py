from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from app.domain.common_domains import IdentifierRefDomain
from app.domain.food_catalog import MeasurementUnit
from app.domain.food_intake import FoodLineDomain
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
    """Query parameters for an establishment's movement listing.

    The date bounds read the event date -- ``food_intakes.received_at`` or
    ``food_outflows.occurred_at`` -- never ``created_at``, so a retroactive
    load falls in the period it actually happened in.
    """

    direction: FoodMovementDirection | None = None
    occurred_from: datetime | None = None
    occurred_to: datetime | None = None


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
class FoodMovementDomain:
    """One movement document -- an intake or an outflow -- with its lines.

    ``food_intakes.received_at`` and ``food_outflows.occurred_at`` are the same
    fact under two names and are normalized to ``occurred_at``; ``direction``
    is what tells the two apart, so a row says which one it is without needing
    the envelope it arrived in.

    ``source`` is annotated ``str`` because the attribute carries a
    ``FoodIntakeSource`` *or* a ``FoodOutflowSource`` -- both ``str``-mixin
    enums with identical members.

    ``items`` are rendered as stored, repeated foods included: a movement may
    legally carry two lines for the same food, and the listing reports what was
    recorded rather than a rollup.
    """

    id: UUID
    direction: FoodMovementDirection
    occurred_at: datetime
    comments: str | None
    source: str
    responsible: ResponsibleRefDomain
    items: list[FoodLineDomain]

    @classmethod
    def _from_movement(
        cls, movement, direction: FoodMovementDirection, occurred_at: datetime
    ) -> "FoodMovementDomain":
        return cls(
            id=movement.id,
            direction=direction,
            occurred_at=occurred_at,
            comments=movement.comments,
            source=movement.source,
            responsible=ResponsibleRefDomain.from_db(movement.responsible),
            items=[FoodLineDomain.from_db(item) for item in movement.items],
        )

    @classmethod
    def from_intake(cls, intake) -> "FoodMovementDomain":
        """Build from an intake row with ``responsible`` and ``items`` (each
        with its ``food``) loaded."""
        return cls._from_movement(intake, FoodMovementDirection.IN, intake.received_at)

    @classmethod
    def from_outflow(cls, outflow) -> "FoodMovementDomain":
        """Build from an outflow row with ``responsible`` and ``items`` (each
        with its ``food``) loaded."""
        return cls._from_movement(
            outflow, FoodMovementDirection.OUT, outflow.occurred_at
        )
