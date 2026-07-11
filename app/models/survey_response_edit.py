import uuid

from sqlalchemy import Column, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import JSONB, UUID

from .base import Base


class SurveyResponseEdit(Base):
    """Append-only audit log of edits to a survey response.

    Trimmed version of the `SubjectEvent` pattern (app/models/subject_event.py):
    no `event_type` column since this table only ever logs edits, and a full
    post-edit `answers` snapshot instead of a structured before/after diff.
    """

    __tablename__ = "survey_response_edits"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    response_id = Column(
        UUID(as_uuid=True),
        ForeignKey("survey_responses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    edited_by_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    answers = Column(JSONB, nullable=False)
    event_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
