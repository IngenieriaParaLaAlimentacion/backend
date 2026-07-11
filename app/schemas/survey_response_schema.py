from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.measurement_schema import EstablishmentRefResponse

# -- Requests --


def validate_event_at(v: datetime) -> datetime:
    if v > datetime.now(timezone.utc):
        raise ValueError("event_at cannot be in the future")
    return v


class SurveyResponseRequest(BaseModel):
    id: UUID | None = Field(
        default=None,
        description=(
            "Client-generated UUID for offline-first idempotency. When provided "
            "it becomes the response's primary key and repeated submissions with "
            "the same id are idempotent. When omitted, the server generates one."
        ),
    )
    survey_id: UUID
    establishment_id: UUID
    answers: dict[str, Any]
    event_at: datetime

    _check_event_at = field_validator("event_at")(validate_event_at)


class SurveyResponseEditRequest(BaseModel):
    id: UUID | None = Field(
        default=None,
        description=(
            "Client-generated UUID identifying this edit attempt, for "
            "offline-first idempotency on retried syncs."
        ),
    )
    answers: dict[str, Any]
    event_at: datetime

    _check_event_at = field_validator("event_at")(validate_event_at)


# -- Responses --


class SurveyResponseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    survey_id: UUID
    establishment_id: UUID
    submitted_by_id: UUID
    answers: dict[str, Any]
    event_at: datetime
    created_at: datetime
    updated_at: datetime


class SurveyRefResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str


class SurveyResponseListItem(BaseModel):
    """An enriched response row for the activity-feed view."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    event_at: datetime
    survey: SurveyRefResponse
    establishment: EstablishmentRefResponse
