from datetime import date, datetime
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, Field, StringConstraints, field_validator

from app.domain.subject import Sex
from app.domain.subject_event import SubjectEventType


class SubjectRequest(BaseModel):
    dni: int = Field(ge=1, le=99_999_999)
    sex: Sex
    name: Annotated[
        str,
        StringConstraints(
            strict=True, strip_whitespace=True, min_length=1, max_length=50
        ),
    ]
    last_name: Annotated[
        str,
        StringConstraints(
            strict=True, strip_whitespace=True, min_length=1, max_length=50
        ),
    ]
    birth_date: date
    is_rural: bool = Field(
        description="Bool indicating if the subject belongs to a rural population"
    )
    is_indigenous: bool = Field(
        description="Bool indicating if the subject belongs to an indigenous population"
    )

    @field_validator("birth_date")
    @classmethod
    def birth_date_not_in_future(cls, v: date) -> date:
        if v > date.today():
            raise ValueError("birth date cannot be in the future")
        return v


class SubjectSummaryResponse(BaseModel):
    id: UUID
    dni: int
    name: str
    last_name: str
    sex: Sex

    model_config = {"from_attributes": True}


class SubjectResponse(SubjectSummaryResponse):
    birth_date: date
    is_rural: bool
    is_indigenous: bool


class EventPayloadResponse(BaseModel):
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None


class SubjectEventResponse(BaseModel):
    event_type: SubjectEventType
    occurred_at: datetime
    actor_id: UUID
    payload: EventPayloadResponse
