from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from app.domain.measurement import MeasurementListItemDomain
from app.domain.subject import SubjectBase
from app.domain.survey_response import SurveyResponseListItemDomain


class ActivityType(StrEnum):
    """Kinds of self-published activity surfaced in the recent-activity feed."""

    SUBJECT = "subject"
    MEASUREMENT = "measurement"
    SURVEY_RESPONSE = "survey_response"


@dataclass
class ActivityListingParams:
    """Query parameters for the current user's activity feed."""

    activity_type: ActivityType | None = None


@dataclass
class ActivityItemDomain:
    """A single entry in a user's self-published recent-activity feed.

    Exactly one of `subject`/`measurement`/`survey_response` is set, matching
    `type`.
    """

    type: ActivityType
    occurred_at: datetime
    subject: SubjectBase | None = None
    measurement: MeasurementListItemDomain | None = None
    survey_response: SurveyResponseListItemDomain | None = None
