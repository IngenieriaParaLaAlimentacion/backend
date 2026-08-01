from dataclasses import dataclass
from datetime import datetime
from enum import Enum, StrEnum
from uuid import UUID


class ResponseType(str, Enum):
    """Response types a survey question can accept."""

    TEXT = "text"
    SINGLE_CHOICE = "single_choice"
    MULTIPLE_CHOICE = "multiple_choice"
    NUMERIC = "numeric"
    DATE = "date"


class SurveyInstrumentType(str, Enum):
    """Whether a survey is the canonical FAO FIES instrument or a custom one."""

    CUSTOM = "custom"
    FIES = "fies"


class SurveyScope(str, Enum):
    """Audience scope of a survey."""

    GENERIC = "generic"
    TARGETED = "targeted"


class SurveySortOrder(StrEnum):
    """Sort orders accepted by the survey listing."""

    NAME_ASC = "name_asc"
    NAME_DESC = "name_desc"
    NEWEST = "newest"
    OLDEST = "oldest"


# Choice-type questions carry options; other types must not.
CHOICE_TYPES = {ResponseType.SINGLE_CHOICE, ResponseType.MULTIPLE_CHOICE}

# Structural bounds and length caps — single source of truth reused by schema + service.
MIN_QUESTIONS = 1
MAX_QUESTIONS = 30
MIN_OPTIONS = 2
MAX_OPTIONS = 20
NAME_MAX = 120
DESCRIPTION_MAX = 1000
QUESTION_TEXT_MAX = 500
OPTION_TEXT_MAX = 200


@dataclass
class OptionInputData:
    """Repository-facing input for a single choice option.

    ``id`` is present only when reconciling an existing option on ``PUT``.
    """

    text: str
    id: UUID | None = None


@dataclass
class QuestionInputData:
    """Repository-facing input for a single question and its options.

    ``id`` is present only when reconciling an existing question on ``PUT``.
    """

    text: str
    response_type: ResponseType
    is_required: bool
    options: list[OptionInputData]
    id: UUID | None = None


@dataclass
class OptionDomain:
    """A single choice option belonging to a question."""

    id: UUID
    text: str
    position: int

    @classmethod
    def from_db(cls, obj) -> "OptionDomain":
        return cls(id=obj.id, text=obj.text, position=obj.position)


@dataclass
class QuestionDomain:
    """A survey question with its (possibly empty) choice options."""

    id: UUID
    text: str
    response_type: ResponseType
    is_required: bool
    position: int
    options: list[OptionDomain]

    @classmethod
    def from_db(cls, obj) -> "QuestionDomain":
        return cls(
            id=obj.id,
            text=obj.text,
            response_type=obj.response_type,
            is_required=obj.is_required,
            position=obj.position,
            options=[OptionDomain.from_db(o) for o in obj.options],
        )


@dataclass
class SurveyDomain:
    """A full survey configuration with its ordered questions and audience."""

    id: UUID
    name: str
    description: str | None
    scope: SurveyScope
    instrument_type: SurveyInstrumentType
    created_by_id: UUID
    is_active: bool
    response_count: int
    questions: list[QuestionDomain]
    establishment_ids: list[UUID]
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_db(cls, obj) -> "SurveyDomain":
        """Build a SurveyDomain from an ORM Survey with loaded relations."""
        return cls(
            id=obj.id,
            name=obj.name,
            description=obj.description,
            scope=obj.scope,
            instrument_type=obj.instrument_type,
            created_by_id=obj.created_by_id,
            is_active=obj.is_active,
            response_count=obj.response_count,
            questions=[QuestionDomain.from_db(q) for q in obj.questions],
            establishment_ids=[e.id for e in obj.establishments],
            created_at=obj.created_at,
            updated_at=obj.updated_at,
        )


@dataclass
class SurveyListItemDomain:
    """A summarized survey row for the listing view."""

    id: UUID
    name: str
    scope: SurveyScope
    is_active: bool
    created_by_id: UUID
    question_count: int
    created_at: datetime

    @classmethod
    def from_db(cls, obj, question_count: int) -> "SurveyListItemDomain":
        """Build a list item from a survey row and its precomputed question count.

        ``question_count`` comes from a subquery in the listing query, so the
        ``questions`` relationship is never loaded for the summary view.
        """
        return cls(
            id=obj.id,
            name=obj.name,
            scope=obj.scope,
            is_active=obj.is_active,
            created_by_id=obj.created_by_id,
            question_count=question_count,
            created_at=obj.created_at,
        )


@dataclass
class SurveyListingParams:
    """Query parameters for a paginated survey listing."""

    search: str | None = None
    created_by: UUID | None = None
    scope: SurveyScope | None = None
    is_active: bool | None = None
    sort_order: SurveySortOrder = SurveySortOrder.NEWEST

    def __post_init__(self) -> None:
        self.search = self.search.strip() or None if self.search else None
