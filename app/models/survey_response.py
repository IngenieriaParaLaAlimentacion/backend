import uuid

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from .base import Base


class SurveyResponse(Base):
    """One set of answers to a survey.

    What the answers are *about* is decided by the survey's ``response_target``:
    a subject, an establishment, or nobody (anonymous). At most one of
    ``subject_id`` / ``establishment_id`` is ever set; both are null for an
    anonymous response.
    """

    __tablename__ = "survey_responses"
    __table_args__ = (
        Index("ix_survey_responses_survey_id_event_at", "survey_id", "event_at"),
        CheckConstraint(
            "num_nonnulls(subject_id, establishment_id) <= 1",
            name="ck_survey_responses_single_target",
        ),
        Index(
            "uq_survey_responses_survey_establishment",
            "survey_id",
            "establishment_id",
            unique=True,
            postgresql_where=text("establishment_id IS NOT NULL"),
        ),
        Index(
            "uq_survey_responses_survey_subject",
            "survey_id",
            "subject_id",
            unique=True,
            postgresql_where=text("subject_id IS NOT NULL"),
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    survey_id = Column(
        UUID(as_uuid=True),
        ForeignKey("surveys.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    subject_id = Column(
        UUID(as_uuid=True),
        ForeignKey("subjects.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    establishment_id = Column(
        UUID(as_uuid=True),
        ForeignKey("establishments.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    submitted_by_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    answers = Column(JSONB, nullable=False)
    score_fies = Column(Integer, nullable=True)
    event_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    survey = relationship("Survey")
    subject = relationship("Subject")
    establishment = relationship("Establishment")
    submitted_by = relationship("User")
