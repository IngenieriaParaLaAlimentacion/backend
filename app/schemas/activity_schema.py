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
    matching ``type``; every other sibling is serialized as null, so adding a
    sibling stays additive for clients.
    """

    model_config = ConfigDict(from_attributes=True)

    type: ActivityType
    occurred_at: datetime
    subject: SubjectSummaryResponse | None = None
    measurement: MeasurementListItem | None = None
    survey_response: SurveyResponseListItem | None = None
    food_intake: FoodMovementListItem | None = None
    food_outflow: FoodMovementListItem | None = None
