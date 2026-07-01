from datetime import datetime
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

from app.domain.activity import ActivityType
from app.schemas.measurement_schema import MeasurementListItem
from app.schemas.subject_schema import SubjectSummaryResponse


class SubjectActivityItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    type: Literal[ActivityType.SUBJECT]
    occurred_at: datetime
    subject: SubjectSummaryResponse


class MeasurementActivityItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    type: Literal[ActivityType.MEASUREMENT]
    occurred_at: datetime
    measurement: MeasurementListItem


ActivityItem = Annotated[
    Union[SubjectActivityItem, MeasurementActivityItem],
    Field(discriminator="type"),
]
