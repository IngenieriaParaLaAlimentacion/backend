from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.domain.food_catalog import MeasurementUnit
from app.domain.food_intake import FoodIntakeOriginType, FoodIntakeSource
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


class FoodMovementSummary(BaseModel):
    """One row of the movement listing: a movement without its lines.

    ``occurred_at`` is the date the movement happened, not when the row was
    written, and ``food_count`` how many *distinct* foods it touched. The
    lines, source and comments come from the detail endpoint. Intake-only
    origin and recurrence are null for outflows.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    direction: FoodMovementDirection
    occurred_at: datetime
    responsible: ResponsibleRefResponse
    food_count: int
    origin_type: FoodIntakeOriginType | None
    is_recurring: bool | None


class FoodMovementDetail(BaseModel):
    """One movement -- an intake or an outflow -- with all of its lines.

    ``source`` is typed as ``FoodIntakeSource`` because ``FoodOutflowSource``
    has identical members and Pydantic coerces a ``str``-mixin enum by value.

    ``items`` is rendered exactly as stored, duplicate food lines included:
    the read path never aggregates. Intake-only origin and recurrence are null
    for outflows.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    direction: FoodMovementDirection
    occurred_at: datetime
    source: FoodIntakeSource
    origin_type: FoodIntakeOriginType | None
    is_recurring: bool | None
    comments: str | None
    responsible: ResponsibleRefResponse
    items: list[FoodLineResponse]
