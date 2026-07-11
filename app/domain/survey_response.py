from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.domain.measurement import EstablishmentRefDomain


@dataclass
class SurveyResponseDomain:
    """A registered survey response."""

    id: UUID
    survey_id: UUID
    establishment_id: UUID
    submitted_by_id: UUID
    answers: dict[str, object]
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
            event_at=obj.event_at,
            created_at=obj.created_at,
            updated_at=obj.updated_at,
        )


@dataclass
class SurveyRefDomain:
    """Minimal survey identity for embedding in a response summary."""

    id: UUID
    name: str


@dataclass
class SurveyResponseListItemDomain:
    """An enriched response row for the activity-feed view.

    No submitter reference: ``/me/activity`` is already scoped to the caller.
    """

    id: UUID
    event_at: datetime
    survey: SurveyRefDomain
    establishment: EstablishmentRefDomain

    @classmethod
    def from_db(cls, obj) -> "SurveyResponseListItemDomain":
        """Build from an ORM SurveyResponse with ``survey``/``establishment`` loaded."""
        return cls(
            id=obj.id,
            event_at=obj.event_at,
            survey=SurveyRefDomain(id=obj.survey.id, name=obj.survey.name),
            establishment=EstablishmentRefDomain.from_db(obj.establishment),
        )
