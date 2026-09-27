import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

from app.domain.survey import (
    ResponseType,
    SurveyResponseTarget,
)

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


# -- Builders --


def _make_option(text: str = "Opción") -> MagicMock:
    o = MagicMock()
    o.id = uuid.uuid4()
    o.text = text
    o.position = 0
    return o


def _make_question(
    response_type: ResponseType = ResponseType.TEXT,
    is_required: bool = False,
    options: list | None = None,
) -> MagicMock:
    q = MagicMock()
    q.id = uuid.uuid4()
    q.text = "¿Pregunta?"
    q.response_type = response_type
    q.is_required = is_required
    q.position = 0
    q.options = options or []
    return q


def _make_survey_orm(
    response_target: SurveyResponseTarget = SurveyResponseTarget.ANONYMOUS,
    questions: list | None = None,
    requires_response_number: bool | None = None,
) -> MagicMock:
    """A MagicMock standing in for an ORM Survey with eager-loaded relations."""
    s = MagicMock()
    s.id = uuid.uuid4()
    s.name = "Encuesta"
    s.description = None
    s.response_target = response_target
    s.requires_response_number = requires_response_number
    s.created_by_id = uuid.uuid4()
    s.is_active = True
    s.response_count = 0
    s.questions = questions or []
    s.created_at = NOW
    s.updated_at = NOW
    return s


def _make_response(
    survey_id: uuid.UUID | None = None,
    subject_id: uuid.UUID | None = None,
    establishment_id: uuid.UUID | None = None,
    submitted_by_id: uuid.UUID | None = None,
    answers: dict | None = None,
    response_number: int = 1,
    event_at: datetime = NOW,
) -> MagicMock:
    """A MagicMock standing in for an ORM SurveyResponse.

    Defaults to an anonymous response: neither target column is set.
    """
    r = MagicMock()
    r.id = uuid.uuid4()
    r.survey_id = survey_id or uuid.uuid4()
    r.subject_id = subject_id
    r.establishment_id = establishment_id
    r.submitted_by_id = submitted_by_id or uuid.uuid4()
    r.answers = answers if answers is not None else {}
    r.response_number = response_number
    r.event_at = event_at
    r.created_at = NOW
    r.updated_at = NOW
    return r


def _apply_update_answers(response, answers, score_fies, response_number, event_at):
    response.answers = answers
    response.score_fies = score_fies
    response.response_number = response_number
    response.event_at = event_at
    return response


# -- Fixtures --

_UNSET = object()
