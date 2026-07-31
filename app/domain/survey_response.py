from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.domain.common_domains import IdentifierRefDomain
from app.domain.measurement import EstablishmentRefDomain
from app.domain.survey import ResponseType


@dataclass
class SurveyResponseDomain:
    """A registered survey response."""

    id: UUID
    survey_id: UUID
    establishment_id: UUID
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
            survey_id=obj.survey_id,
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
    event_at: datetime
    survey: IdentifierRefDomain
    establishment: EstablishmentRefDomain

    @classmethod
    def from_db(cls, obj) -> "SurveyResponseListItemDomain":
        """Build from an ORM SurveyResponse with ``survey``/``establishment`` loaded."""
        return cls(
            id=obj.id,
            event_at=obj.event_at,
            survey=IdentifierRefDomain(id=obj.survey.id, name=obj.survey.name),
            establishment=EstablishmentRefDomain.from_db(obj.establishment),
        )


@dataclass
class SurveyResponseDashboardItemDomain:
    """An enriched response row for the admin/analyst dashboard view.

    Unlike SurveyResponseListItemDomain (activity feed), this includes who
    submitted the response, since here the viewer isn't the submitter.
    """

    id: UUID
    event_at: datetime
    survey: IdentifierRefDomain
    establishment: EstablishmentRefDomain
    submitted_by: IdentifierRefDomain
    score_fies: int | None

    @classmethod
    def from_db(cls, obj) -> "SurveyResponseDashboardItemDomain":
        """Build from an ORM SurveyResponse with survey/establishment/submitted_by
        loaded."""
        return cls(
            id=obj.id,
            event_at=obj.event_at,
            survey=IdentifierRefDomain(id=obj.survey.id, name=obj.survey.name),
            establishment=EstablishmentRefDomain.from_db(obj.establishment),
            submitted_by=IdentifierRefDomain(
                id=obj.submitted_by.id, name=obj.submitted_by.name
            ),
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
    event_at: datetime
    survey: IdentifierRefDomain
    establishment: EstablishmentRefDomain
    submitted_by: IdentifierRefDomain
    score_fies: int | None
    answers: list[QuestionAnswerDomain]

    @classmethod
    def from_db(cls, obj) -> "SurveyResponseDetailDomain":
        """Build from an ORM SurveyResponse with survey.questions(.options),
        establishment and submitted_by eager-loaded."""
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
            event_at=obj.event_at,
            survey=IdentifierRefDomain(id=obj.survey.id, name=obj.survey.name),
            establishment=EstablishmentRefDomain.from_db(obj.establishment),
            submitted_by=IdentifierRefDomain(
                id=obj.submitted_by.id, name=obj.submitted_by.name
            ),
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
    """Filters for a survey's response listing: establishment, event
    date range, and geographic zone (establishment's city/province)."""

    establishment_id: UUID | None = None
    event_at_from: datetime | None = None
    event_at_to: datetime | None = None
    city: str | None = None
    province: str | None = None

    def __post_init__(self) -> None:
        self.city = self.city.strip() or None if self.city else None
        self.province = self.province.strip() or None if self.province else None


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
        self.city = self.city.strip() or None if self.city else None
        self.province = self.province.strip() or None if self.province else None


@dataclass
class SurveyResponseSummaryDomain:
    """Aggregated metrics over survey responses: total responses, distinct
    participating establishments, and the most recent event_at — all
    computed over whatever SurveyResponseSummaryParams filtered."""

    response_count: int
    participating_establishments_count: int
    last_event_at: datetime | None
