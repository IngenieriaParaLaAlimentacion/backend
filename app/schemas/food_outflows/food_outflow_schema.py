from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.food_outflow import FoodOutflowCategory, FoodOutflowSource
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
    comments: str | None = Field(
        default=None,
        max_length=500,
        description=(
            "Optional specification of category 'other'; omit for every other category."
        ),
    )
    category: FoodOutflowCategory = Field(
        default=FoodOutflowCategory.OTHER,
        description=(
            "Why food left stock. Omission temporarily maps legacy clients to 'other'."
        ),
    )
    source: FoodOutflowSource = FoodOutflowSource.MANUAL
    items: list[FoodLineRequest] = Field(min_length=1)

    _check_occurred_at = field_validator("occurred_at")(validate_not_future_datetime)

    @model_validator(mode="after")
    def comments_only_for_other(self) -> "FoodOutflowRequest":
        """Accept comments only when the outflow category is other."""
        if (
            self.category != FoodOutflowCategory.OTHER
            and "comments" in self.model_fields_set
        ):
            raise ValueError("comments may be supplied only for category 'other'")
        return self


# -- Response --


class FoodOutflowResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    establishment_id: UUID
    responsible_id: UUID
    occurred_at: datetime
    comments: str | None
    category: FoodOutflowCategory
    source: FoodOutflowSource
    created_at: datetime
    items: list[FoodLineResponse]
