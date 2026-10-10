from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.domain.food_intake import FoodIntakeOriginType, FoodIntakeSource
from app.schemas.food_intakes.food_intake_schema import FoodLineResponse
from app.schemas.measurements.measurement_schema import EstablishmentRefResponse

# -- Response --


class FoodMovementListItem(BaseModel):
    """A food intake or outflow row for the activity-feed view.

    One schema serves both directions; which one a row is comes from the
    item's ``type``. ``source`` is typed as ``FoodIntakeSource`` because
    ``FoodOutflowSource`` has identical members and Pydantic coerces a
    ``str``-mixin enum by value.

    ``items`` is rendered exactly as stored, duplicate food lines included:
    the read path never aggregates.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    occurred_at: datetime
    establishment: EstablishmentRefResponse
    source: FoodIntakeSource
    origin_type: FoodIntakeOriginType | None
    is_recurring: bool | None
    comments: str | None
    items: list[FoodLineResponse]
