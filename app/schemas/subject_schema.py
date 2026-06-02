from datetime import date, datetime, timezone
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, Field, StringConstraints, field_validator

from app.domain.subject import Sex
from app.domain.subject_event import SubjectEventType

ValidNameStr = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=50),
]


def validate_date(v: date | None) -> date | None:
    if v is not None and v > datetime.now(timezone.utc).date():
        raise ValueError("birth date cannot be in the future")
    return v


class SubjectRequest(BaseModel):
    dni: int = Field(ge=1, le=99_999_999)
    sex: Sex
    name: ValidNameStr
    last_name: ValidNameStr
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
    name: ValidNameStr | None = None
    last_name: ValidNameStr | None = None

    birth_date: date | None = None
    is_rural: bool | None = None
    is_indigenous: bool | None = None

    _check_birth_date = field_validator("birth_date")(validate_date)

    def to_update_dict(self) -> dict:
        """Return only the fields explicitly set in the request."""
        return self.model_dump(exclude_unset=True)


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
