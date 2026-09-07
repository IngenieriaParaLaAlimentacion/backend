from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.food_outflow import FoodOutflowSource
from app.schemas.food_intakes.food_intake_schema import (
    FoodLineRequest,
    FoodLineResponse,
)
from app.schemas.types import ClientGeneratedId
from app.utils.dates import validate_not_future_datetime

# -- Request --


class FoodOutflowRequest(BaseModel):
    id: ClientGeneratedId
    establishment_id: UUID
    occurred_at: datetime = Field(
        description="When the food left. May predate the load for retroactive entries."
    )
    comments: str | None = Field(default=None, max_length=500)
    source: FoodOutflowSource = FoodOutflowSource.MANUAL
    items: list[FoodLineRequest] = Field(min_length=1)

    _check_occurred_at = field_validator("occurred_at")(validate_not_future_datetime)


# -- Response --


class FoodOutflowResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    establishment_id: UUID
    responsible_id: UUID
    occurred_at: datetime
    comments: str | None
    source: FoodOutflowSource
    created_at: datetime
    items: list[FoodLineResponse]
