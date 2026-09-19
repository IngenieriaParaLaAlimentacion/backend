from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.domain.food_catalog import MeasurementUnit
from app.domain.food_intake import FoodIntakeSource
from app.domain.food_stock import FoodMovementDirection
from app.schemas.common import IdentifierRefSchema
from app.schemas.food_intakes.food_intake_schema import FoodLineResponse
from app.schemas.measurements.measurement_schema import ResponsibleRefResponse


class FoodStockItem(BaseModel):
    """How much of one food an establishment holds right now."""

    model_config = ConfigDict(from_attributes=True)

    food: IdentifierRefSchema
    category: IdentifierRefSchema
    unit: MeasurementUnit
    quantity: Decimal
    updated_at: datetime


class FoodMovementItem(BaseModel):
    """One movement document -- an intake or an outflow -- with its lines.

    ``direction`` is what distinguishes the two, and ``occurred_at`` is the
    date the movement happened, not when the row was written. The
    establishment is not repeated per row: the listing is already scoped to
    the one in the path.

    ``source`` is typed as ``FoodIntakeSource`` because ``FoodOutflowSource``
    has identical members and Pydantic coerces a ``str``-mixin enum by value.

    ``items`` is rendered exactly as stored, duplicate food lines included:
    the read path never aggregates.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    direction: FoodMovementDirection
    occurred_at: datetime
    source: FoodIntakeSource
    comments: str | None
    responsible: ResponsibleRefResponse
    items: list[FoodLineResponse]
