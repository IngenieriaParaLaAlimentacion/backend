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
        cls, movement, direction: FoodMovementDirection
    ) -> "FoodMovementDomain":
        return cls(
            id=movement.id,
            direction=direction,
            occurred_at=movement.occurred_at,
            comments=movement.comments,
            source=movement.source,
            responsible=ResponsibleRefDomain.from_db(movement.responsible),
            items=[FoodLineDomain.from_db(item) for item in movement.items],
        )

    @classmethod
    def from_intake(cls, intake) -> "FoodMovementDomain":
        """Build from an intake row with ``responsible`` and ``items`` (each
        with its ``food``) loaded."""
        return cls._from_movement(intake, FoodMovementDirection.IN)

    @classmethod
    def from_outflow(cls, outflow) -> "FoodMovementDomain":
        """Build from an outflow row with ``responsible`` and ``items`` (each
        with its ``food``) loaded."""
        return cls._from_movement(outflow, FoodMovementDirection.OUT)
