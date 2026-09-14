from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from app.domain.food_intake import FoodMovementListItemDomain
from app.domain.measurement import MeasurementListItemDomain
from app.domain.subject import SubjectBase
from app.domain.survey_response import SurveyResponseListItemDomain


class ActivityType(StrEnum):
    """Kinds of self-published activity surfaced in the recent-activity feed."""

    SUBJECT = "subject"
    MEASUREMENT = "measurement"
    SURVEY_RESPONSE = "survey_response"
    FOOD_INTAKE = "food_intake"
    FOOD_OUTFLOW = "food_outflow"


@dataclass
class ActivityListingParams:
    """Query parameters for the current user's activity feed."""

    activity_type: ActivityType | None = None


@dataclass
class ActivityItemDomain:
    """A single entry in a user's self-published recent-activity feed.

    Exactly one of `subject`/`measurement`/`survey_response`/`food_intake`/
    `food_outflow` is set, matching `type`; the rest are None.

    `occurred_at` is always the domain event time of the underlying row
    (`subject_events.occurred_at`, `measurements.measured_at`,
    `survey_responses.event_at`, `food_intakes.received_at`,
    `food_outflows.occurred_at`), never `created_at`.
    """

    type: ActivityType
    occurred_at: datetime
    subject: SubjectBase | None = None
    measurement: MeasurementListItemDomain | None = None
    survey_response: SurveyResponseListItemDomain | None = None
    food_intake: FoodMovementListItemDomain | None = None
    food_outflow: FoodMovementListItemDomain | None = None
