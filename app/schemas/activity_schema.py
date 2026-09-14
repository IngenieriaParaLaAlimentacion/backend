from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.domain.activity import ActivityType
from app.schemas.food_movements.food_movement_schema import FoodMovementListItem
from app.schemas.measurements.measurement_schema import MeasurementListItem
from app.schemas.subjects.subject_schema import SubjectSummaryResponse
from app.schemas.surveys.survey_response_schema import SurveyResponseListItem

# -- Response --


class ActivityItemResponse(BaseModel):
    """A single entry in a user's recent-activity feed.

    Not a discriminated union: exactly one payload sibling is populated,
    matching ``type``; every other sibling is serialized as null. Adding a
    sibling is therefore additive for clients, at the cost of one more null
    key on every item.

    ``food_intake`` and ``food_outflow`` share the same payload schema; the
    direction is carried by ``type`` and by which key is set.
    """

    model_config = ConfigDict(from_attributes=True)

    type: ActivityType
    occurred_at: datetime
    subject: SubjectSummaryResponse | None = None
    measurement: MeasurementListItem | None = None
    survey_response: SurveyResponseListItem | None = None
    food_intake: FoodMovementListItem | None = None
    food_outflow: FoodMovementListItem | None = None
