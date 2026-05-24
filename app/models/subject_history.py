import uuid

from sqlalchemy import Column, DateTime, ForeignKey, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.domain.subject import SubjectEventType

from .base import Base


class SubjectEvent(Base):
    """Append-only audit log of every action taken on a subject."""

    __tablename__ = "subject_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    subject_id = Column(
        UUID(as_uuid=True),
        ForeignKey("subjects.id", ondelete="RESTRICT"),
        nullable=False,
    )
    actor_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    event_type = Column(
        SAEnum(SubjectEventType, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    occurred_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    payload = Column(JSONB, nullable=True)
