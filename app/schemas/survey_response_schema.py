from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.survey import ResponseType
from app.schemas.common_schemas import IdentifierRefSchema
from app.schemas.measurement_schema import EstablishmentRefResponse, SubjectRefResponse
from app.utils.dates import is_future_date

AnswerValue = str | int | float | list[str]


def validate_event_at(v: datetime) -> datetime:
    if is_future_date(v):
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
    subject_id: UUID | None = Field(
        default=None,
        description=("Required when the survey targets subjects, forbidden otherwise."),
    )
    establishment_id: UUID | None = Field(
        default=None,
        description=(
            "Required when the survey targets establishments, forbidden "
            "otherwise. Any establishment is accepted — it records who "
            "answered, not who is allowed to."
        ),
    )
    answers: dict[str, AnswerValue]
    event_at: datetime = Field(
        description=(
            "When the respondent actually completed the survey, client-supplied. "
            "May predate the server's persistence time for offline-first syncs."
        ),
    )

    _check_event_at = field_validator("event_at")(validate_event_at)


class SurveyRefResponse(IdentifierRefSchema):
    pass


class UserRefResponse(IdentifierRefSchema):
    pass


class ExistingResponseRef(BaseModel):
    """The response already recorded for a target, returned in the 409 body
    as the ``existing_response`` member."""

    id: UUID
    submitted_by: UserRefResponse
    event_at: datetime


class SurveyResponseEditRequest(BaseModel):
    id: UUID | None = Field(
        default=None,
        description=(
            "Client-generated UUID identifying this edit attempt, for "
            "offline-first idempotency on retried syncs."
        ),
    )
    answers: dict[str, AnswerValue]
    event_at: datetime = Field(
        description=(
            "When the edit was actually made, client-supplied. Used for "
            "last-write-wins conflict resolution against the response's "
            "current event_at."
        ),
    )

    _check_event_at = field_validator("event_at")(validate_event_at)


class SurveyResponseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    survey_id: UUID
    subject_id: UUID | None
    establishment_id: UUID | None
    submitted_by_id: UUID
    answers: dict[str, Any]
    score_fies: int | None
    event_at: datetime
    created_at: datetime
    updated_at: datetime


class SurveyResponseListItem(BaseModel):
    """An enriched response row for the activity-feed view."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    event_at: datetime
    survey: SurveyRefResponse
    establishment: EstablishmentRefResponse | None
    subject: SubjectRefResponse | None


class SurveyResponseDashboardItem(BaseModel):
    """An enriched response row for the admin/analyst dashboard view."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    event_at: datetime
    survey: SurveyRefResponse
    establishment: EstablishmentRefResponse | None
    subject: SubjectRefResponse | None
    submitted_by: UserRefResponse
    score_fies: int | None


class QuestionAnswerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    question_id: UUID
    question_text: str
    response_type: ResponseType
    value: AnswerValue | None
    value_label: str | list[str] | None = None


class SurveyResponseDetailResponse(BaseModel):
    """Full response detail for the dashboard: every question in the
    survey plus the value this specific user answered for it."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    event_at: datetime
    survey: SurveyRefResponse
    establishment: EstablishmentRefResponse | None
    subject: SubjectRefResponse | None
    submitted_by: UserRefResponse
    score_fies: int | None
    answers: list[QuestionAnswerResponse]
