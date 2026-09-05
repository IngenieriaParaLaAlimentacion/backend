from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.domain.food_catalog import MeasurementUnit
from app.domain.food_stock import FoodMovementDirection
from app.schemas.common import IdentifierRefSchema


class FoodStockItem(BaseModel):
    """How much of one food an establishment holds right now."""

    model_config = ConfigDict(from_attributes=True)

    food: IdentifierRefSchema
    category: IdentifierRefSchema
    unit: MeasurementUnit
    quantity: Decimal
    updated_at: datetime


class FoodMovementItem(BaseModel):
    """One movement of a food's balance, in the per-food history view."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    direction: FoodMovementDirection
    occurred_at: datetime
    quantity: Decimal
    comments: str | None
