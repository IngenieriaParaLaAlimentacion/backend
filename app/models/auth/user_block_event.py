import uuid

from sqlalchemy import Column, DateTime, ForeignKey, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID

from app.domain.user_block_event import UserBlockEventType

from ..base import Base


class UserBlockEvent(Base):
    """Append-only audit log of every block and unblock of a user."""

    __tablename__ = "user_block_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    actor_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    event_type = Column(
        SAEnum(UserBlockEventType, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    occurred_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
