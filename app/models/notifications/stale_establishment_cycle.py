import uuid

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.models.base import Base


class StaleEstablishmentCycle(Base):
    """Current inactivity-notice progression for one establishment."""

    __tablename__ = "stale_establishment_cycles"
    __table_args__ = (
        UniqueConstraint(
            "establishment_id",
            name="uq_stale_establishment_cycles_establishment_id",
        ),
        CheckConstraint(
            "next_threshold_hours IS NULL OR next_threshold_hours IN (168, 336, 504)",
            name="ck_stale_cycles_next_threshold_hours",
        ),
        CheckConstraint(
            "(next_threshold_hours IS NULL) = (next_due_at IS NULL)",
            name="ck_stale_cycles_next_threshold_due_pair",
        ),
        Index(
            "ix_stale_establishment_cycles_next_due_at",
            "next_due_at",
            postgresql_where=text("next_due_at IS NOT NULL"),
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    establishment_id = Column(
        UUID(as_uuid=True),
        ForeignKey("establishments.id", ondelete="CASCADE"),
        nullable=False,
    )
    last_outflow_at = Column(DateTime(timezone=True), nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=False)
    next_threshold_hours = Column(SmallInteger, nullable=True)
    next_due_at = Column(DateTime(timezone=True), nullable=True)

    establishment = relationship(
        "Establishment", back_populates="stale_notification_cycle"
    )
    delivery_jobs = relationship(
        "PushDeliveryJob",
        back_populates="stale_cycle",
        passive_deletes=True,
    )
