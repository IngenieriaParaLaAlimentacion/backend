from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.domain.activity import ActivityType
from app.schemas.measurement_schema import MeasurementListItem
from app.schemas.subject_schema import SubjectSummaryResponse


class ActivityItemResponse(BaseModel):
    """A single entry in a user's recent-activity feed.

    ``subject``/``measurement`` are populated based on ``type``; the other is null.
    """

    model_config = ConfigDict(from_attributes=True)

    type: ActivityType
    occurred_at: datetime
    subject: SubjectSummaryResponse | None = None
    measurement: MeasurementListItem | None = None
