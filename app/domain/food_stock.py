from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from app.domain.common_domains import IdentifierRefDomain
from app.domain.food_catalog import MeasurementUnit


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
    """One movement of a food's balance, for the per-food history view."""

    id: UUID
    direction: FoodMovementDirection
    occurred_at: datetime
    quantity: Decimal
    comments: str | None

    @classmethod
    def from_row(cls, row) -> "FoodMovementDomain":
        """Build from a row of the intake/outflow union query."""
        return cls(
            id=row.id,
            direction=FoodMovementDirection(row.direction),
            occurred_at=row.occurred_at,
            quantity=row.quantity,
            comments=row.comments,
        )
