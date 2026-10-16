from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TypeVar
from uuid import UUID

from app.domain.common_domains import IdentifierRefDomain, normalize_optional_str
from app.domain.measurement import EstablishmentRefDomain, SubjectRefDomain
from app.domain.survey import ResponseType

RefT = TypeVar("RefT")


class SurveyResponseSortOrder(StrEnum):
    """Sort orders accepted by a survey's response listing."""

    EVENT_AT_DESC = "event_at_desc"
    EVENT_AT_ASC = "event_at_asc"
    CREATED_AT_DESC = "created_at_desc"
    CREATED_AT_ASC = "created_at_asc"


def _optional_ref(obj: object, builder: Callable[[object], RefT]) -> RefT | None:
    """Build a nested ref, or None when the relation is not set."""
    return builder(obj) if obj is not None else None


@dataclass
class SubmittedByRefDomain(IdentifierRefDomain):
    """Minimal user reference for who submitted a survey response."""

    last_name: str

    @classmethod
    def from_db(cls, obj) -> "SubmittedByRefDomain":
        return cls(id=obj.id, name=obj.name, last_name=obj.last_name)


@dataclass
class SurveyResponseDomain:
    """A registered survey response."""

    id: UUID
    response_number: int | None
    survey_id: UUID
    subject_id: UUID | None
    establishment_id: UUID | None
    submitted_by_id: UUID
    answers: dict[str, object]
    score_fies: int | None
    event_at: datetime
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_db(cls, obj) -> "SurveyResponseDomain":
        """Build a SurveyResponseDomain from an ORM SurveyResponse."""
        return cls(
            id=obj.id,
            response_number=obj.response_number,
            survey_id=obj.survey_id,
            subject_id=obj.subject_id,
            establishment_id=obj.establishment_id,
            submitted_by_id=obj.submitted_by_id,
            answers=obj.answers,
            score_fies=obj.score_fies,
            event_at=obj.event_at,
            created_at=obj.created_at,
            updated_at=obj.updated_at,
        )


@dataclass
class SurveyResponseListItemDomain:
    """An enriched response row for the activity-feed view.

    No submitter reference: ``/me/activity`` is already scoped to the caller.
    """

    id: UUID
    response_number: int | None
    event_at: datetime
    survey: IdentifierRefDomain
    establishment: EstablishmentRefDomain | None
    subject: SubjectRefDomain | None

    @classmethod
    def from_db(cls, obj) -> "SurveyResponseListItemDomain":
        """Build from an ORM SurveyResponse with ``survey``/``establishment``/
        ``subject`` loaded."""
        return cls(
            id=obj.id,
            response_number=obj.response_number,
            event_at=obj.event_at,
            survey=IdentifierRefDomain.from_db(obj.survey),
            establishment=_optional_ref(
                obj.establishment, EstablishmentRefDomain.from_db
            ),
            subject=_optional_ref(obj.subject, SubjectRefDomain.from_db),
        )


@dataclass
class SurveyResponseDashboardItemDomain:
    """An enriched response row for the admin/analyst dashboard view.

    Unlike SurveyResponseListItemDomain (activity feed), this includes who
    submitted the response, since here the viewer isn't the submitter.
    """

    id: UUID
    response_number: int | None
    event_at: datetime
    survey: IdentifierRefDomain
    establishment: EstablishmentRefDomain | None
    subject: SubjectRefDomain | None
    submitted_by: SubmittedByRefDomain
    score_fies: int | None

    @classmethod
    def from_db(cls, obj) -> "SurveyResponseDashboardItemDomain":
        """Build from an ORM SurveyResponse with survey/establishment/subject/
        submitted_by loaded."""
        return cls(
            id=obj.id,
            response_number=obj.response_number,
            event_at=obj.event_at,
            survey=IdentifierRefDomain.from_db(obj.survey),
            establishment=_optional_ref(
                obj.establishment, EstablishmentRefDomain.from_db
            ),
            subject=_optional_ref(obj.subject, SubjectRefDomain.from_db),
            submitted_by=SubmittedByRefDomain.from_db(obj.submitted_by),
            score_fies=obj.score_fies,
        )


@dataclass
class QuestionAnswerDomain:
    """One question's text alongside the value that user registered for it,
    with choice answers resolved to their option text for display."""

    question_id: UUID
    question_text: str
    response_type: ResponseType
    value: object | None
    value_label: str | list[str] | None


@dataclass
class SurveyResponseDetailDomain:
    """Full detail of one response for the dashboard: every question in
    the survey, its text, and the value that specific user registered —
    resolved to option text when the question is choice-based."""

    id: UUID
    response_number: int | None
    event_at: datetime
    survey: IdentifierRefDomain
    establishment: EstablishmentRefDomain | None
    subject: SubjectRefDomain | None
    submitted_by: SubmittedByRefDomain
    score_fies: int | None
    answers: list[QuestionAnswerDomain]

    @classmethod
    def from_db(cls, obj) -> "SurveyResponseDetailDomain":
        """Build from an ORM SurveyResponse with survey.questions(.options),
        establishment, subject and submitted_by eager-loaded."""
        answers = [
            QuestionAnswerDomain(
                question_id=question.id,
                question_text=question.text,
                response_type=question.response_type,
                value=obj.answers.get(str(question.id)),
                value_label=cls._resolve_label(
                    question, obj.answers.get(str(question.id))
                ),
            )
            for question in sorted(obj.survey.questions, key=lambda q: q.position)
        ]
        return cls(
            id=obj.id,
            response_number=obj.response_number,
            event_at=obj.event_at,
            survey=IdentifierRefDomain.from_db(obj.survey),
            establishment=_optional_ref(
                obj.establishment, EstablishmentRefDomain.from_db
            ),
            subject=_optional_ref(obj.subject, SubjectRefDomain.from_db),
            submitted_by=SubmittedByRefDomain.from_db(obj.submitted_by),
            score_fies=obj.score_fies,
            answers=answers,
        )

    @staticmethod
    def _resolve_label(question, value) -> str | list[str] | None:
        """Resolve a choice answer's option id(s) to their display text.
        Non-choice questions and unanswered questions return None."""
        if value is None:
            return None
        option_by_id = {str(o.id): o.text for o in question.options}
        if question.response_type == ResponseType.SINGLE_CHOICE:
            return option_by_id.get(value)
        if question.response_type == ResponseType.MULTIPLE_CHOICE:
            return [option_by_id[v] for v in value if v in option_by_id]
        return None


@dataclass
class SurveyResponseListingParams:
    """Filters and sort order for a survey's response listing: subject,
    establishment, event date range, and geographic zone (establishment's
    city/province), and the hand-entered response number — exactly, or by
    range."""

    subject_id: UUID | None = None
    establishment_id: UUID | None = None
    event_at_from: datetime | None = None
    event_at_to: datetime | None = None
    city: str | None = None
    province: str | None = None
    response_number: int | None = None
    response_number_from: int | None = None
    response_number_to: int | None = None
    sort_order: SurveyResponseSortOrder = SurveyResponseSortOrder.EVENT_AT_DESC

    def __post_init__(self) -> None:
        self.city = normalize_optional_str(self.city)
        self.province = normalize_optional_str(self.province)


@dataclass
class SurveyResponseSummaryParams:
    """Filters for the survey response summary endpoint. Same shape
    as SurveyResponseListingParams plus an optional survey_id, since here no
    survey is preselected — every filter is optional."""

    survey_id: UUID | None = None
    establishment_id: UUID | None = None
    event_at_from: datetime | None = None
    event_at_to: datetime | None = None
    city: str | None = None
    province: str | None = None

    def __post_init__(self) -> None:
        self.city = normalize_optional_str(self.city)
        self.province = normalize_optional_str(self.province)


@dataclass
class SurveyResponseSummaryDomain:
    """Aggregated metrics over survey responses: total responses, distinct
    participating establishments, and the most recent event_at — all
    computed over whatever SurveyResponseSummaryParams filtered."""

    response_count: int
    participating_establishments_count: int
    last_event_at: datetime | None
