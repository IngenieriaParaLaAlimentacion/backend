from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator

from app.domain.food_catalog import MeasurementUnit
from app.domain.food_intake import FoodIntakeOriginType, FoodIntakeSource
from app.schemas.common import IdentifierRefSchema
from app.schemas.types import ClientGeneratedId
from app.utils.dates import validate_not_future_datetime

# -- Request --


class FoodLineRequest(BaseModel):
    food_id: UUID
    quantity: Decimal = Field(
        gt=0,
        max_digits=10,
        decimal_places=3,
        description=(
            "How much arrived, in the food's own base unit. The unit is not "
            "sent: it is defined by the catalog entry this line references."
        ),
    )


class FoodIntakeRequest(BaseModel):
    id: ClientGeneratedId
    establishment_id: UUID
    occurred_at: datetime = Field(
        description=(
            "When the food arrived. May predate the load for retroactive entries."
        )
    )
    comments: str | None = Field(default=None, max_length=500)
    source: FoodIntakeSource = FoodIntakeSource.MANUAL
    origin_type: FoodIntakeOriginType = Field(
        description="Type of food supplier or donor."
    )
    is_recurring: StrictBool = Field(
        description="Whether this is a recurring contribution."
    )
    items: list[FoodLineRequest] = Field(min_length=1)

    _check_occurred_at = field_validator("occurred_at")(validate_not_future_datetime)


# -- Response --


class FoodLineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    food: IdentifierRefSchema
    unit: MeasurementUnit
    quantity: Decimal


class FoodIntakeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    establishment_id: UUID
    responsible_id: UUID
    occurred_at: datetime
    comments: str | None
    source: FoodIntakeSource
    origin_type: FoodIntakeOriginType
    is_recurring: bool
    photo_key: str | None
    created_at: datetime
    items: list[FoodLineResponse]
