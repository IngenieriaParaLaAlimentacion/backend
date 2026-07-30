from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.subject import Sex
from app.domain.subject_event import SubjectEventType
from app.schemas.types import ValidStr
from app.utils.dates import today_in_argentina


def validate_date(v: date | None) -> date | None:
    if v is not None and v > today_in_argentina():
        raise ValueError("birth date cannot be in the future")
    return v


# -- Request --


class SubjectRequest(BaseModel):
    id: UUID | None = Field(
        default=None,
        description=(
            "Client-generated UUID for offline-first idempotency. When provided it "
            "becomes the subject's primary key and repeated submissions with the same "
            "id are idempotent. When omitted, the server generates one."
        ),
    )
    dni: int = Field(ge=1, le=99_999_999)
    sex: Sex
    name: ValidStr
    last_name: ValidStr
    birth_date: date
    is_rural: bool = Field(
        description="Bool indicating if the subject belongs to a rural population"
    )
    is_indigenous: bool = Field(
        description="Bool indicating if the subject belongs to an indigenous population"
    )

    _check_birth_date = field_validator("birth_date")(validate_date)


class SubjectUpdateRequest(BaseModel):
    dni: int | None = Field(default=None, ge=1, le=99_999_999)
    sex: Sex | None = None
    name: ValidStr | None = None
    last_name: ValidStr | None = None

    birth_date: date | None = None
    is_rural: bool | None = None
    is_indigenous: bool | None = None

    _check_birth_date = field_validator("birth_date")(validate_date)

    def to_update_dict(self) -> dict:
        """Return only the fields explicitly set in the request."""
        return self.model_dump(exclude_unset=True)


# -- Response --


class SubjectSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    dni: int
    name: str
    last_name: str
    sex: Sex


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
