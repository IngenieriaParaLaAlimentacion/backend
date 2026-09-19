from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.domain.food_catalog import MeasurementUnit
from app.domain.food_stock import FoodMovementDirection
from app.schemas.common import IdentifierRefSchema
from app.schemas.measurements.measurement_schema import ResponsibleRefResponse


class FoodStockItem(BaseModel):
    """How much of one food an establishment holds right now."""

    model_config = ConfigDict(from_attributes=True)

    food: IdentifierRefSchema
    category: IdentifierRefSchema
    unit: MeasurementUnit
    quantity: Decimal
    updated_at: datetime


class FoodMovementSummary(BaseModel):
    """One row of the movement listing: a movement without its lines.

    ``occurred_at`` is the date the movement happened, not when the row was
    written, and ``food_count`` how many *distinct* foods it touched. The
    lines, source and comments come from the detail endpoint.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    direction: FoodMovementDirection
    occurred_at: datetime
    responsible: ResponsibleRefResponse
    food_count: int
