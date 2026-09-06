from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.survey import (
    DESCRIPTION_MAX,
    NAME_MAX,
    OPTION_TEXT_MAX,
    QUESTION_TEXT_MAX,
    ResponseType,
    SurveyInstrumentType,
    SurveyResponseTarget,
)


def _trimmed_or_error(value: str) -> str:
    """Trim ``value`` and reject it if nothing remains."""
    trimmed = value.strip()
    if not trimmed:
        raise ValueError("must not be blank")
    return trimmed


# -- Requests --


class OptionInput(BaseModel):
    """A choice option in a create/update payload."""

    id: UUID | None = Field(
        default=None,
        description="Existing option id when editing; omit to create a new option.",
    )
    text: str = Field(min_length=1, max_length=OPTION_TEXT_MAX)

    @field_validator("text")
    @classmethod
    def _trim_text(cls, v: str) -> str:
        return _trimmed_or_error(v)


class QuestionInput(BaseModel):
    """A question in a create/update payload."""

    id: UUID | None = Field(
        default=None,
        description="Existing question id when editing; omit to create a new question.",
    )
    text: str = Field(min_length=1, max_length=QUESTION_TEXT_MAX)
    response_type: ResponseType
    is_required: bool
    options: list[OptionInput] = Field(default_factory=list)

    @field_validator("text")
    @classmethod
    def _trim_text(cls, v: str) -> str:
        return _trimmed_or_error(v)


class SurveyCreateRequest(BaseModel):
    """Full declarative survey configuration for creation.

    Field-level shape (lengths, non-blank) is validated here; semantic structural
    rules (question/option counts, duplicate options) live in the service so they
    surface as RFC 7807 problem responses.
    """

    name: str = Field(min_length=1, max_length=NAME_MAX)
    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX)
    response_target: SurveyResponseTarget = Field(
        description=(
            "What each response is about: a subject, an establishment, or "
            "nobody in particular. Locked once the survey has responses."
        )
    )
    instrument_type: SurveyInstrumentType = SurveyInstrumentType.CUSTOM
    questions: list[QuestionInput] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def _trim_name(cls, v: str) -> str:
        return _trimmed_or_error(v)

    @field_validator("description")
    @classmethod
    def _trim_description(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return v.strip() or None


class SurveyUpdateRequest(SurveyCreateRequest):
    """Declarative survey configuration for a reconciling ``PUT`` (same shape as
    create; question/option ids identify rows to keep)."""


class SurveyStatusRequest(BaseModel):
    """Activate/deactivate a survey."""

    is_active: bool


# -- Responses --


class OptionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    text: str
    position: int


class QuestionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    text: str
    response_type: ResponseType
    is_required: bool
    position: int
    options: list[OptionResponse]


class SurveyDetailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str | None
    response_target: SurveyResponseTarget
    is_active: bool
    created_by_id: UUID
    response_count: int
    questions: list[QuestionResponse]
    created_at: datetime
    updated_at: datetime


class SurveyListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    response_target: SurveyResponseTarget
    is_active: bool
    created_by_id: UUID
    question_count: int
    response_count: int
    created_at: datetime


# -- Template (read-only, un-persisted draft the backoffice can pre-fill) --


class TemplateOption(BaseModel):
    text: str
    position: int


class TemplateQuestion(BaseModel):
    text: str
    response_type: ResponseType
    is_required: bool
    position: int
    options: list[TemplateOption]


class SurveyTemplateResponse(BaseModel):
    """A ready-to-edit survey draft (no ids). ``name`` is left blank for the author."""

    name: str
    description: str | None
    response_target: SurveyResponseTarget
    questions: list[TemplateQuestion]
