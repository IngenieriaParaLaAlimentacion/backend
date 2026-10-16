import uuid

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.models.base import Base


class PushDeliveryJob(Base):
    """Ephemeral, lease-based FCM work deleted after terminal handling."""

    __tablename__ = "push_delivery_jobs"
    __table_args__ = (
        UniqueConstraint(
            "stale_cycle_id",
            "threshold_hours",
            "device_id",
            name="uq_push_delivery_jobs_cycle_threshold_device",
        ),
        CheckConstraint(
            "threshold_hours IN (168, 336, 504)",
            name="ck_push_delivery_jobs_threshold_hours",
        ),
        CheckConstraint(
            "attempt_count >= 0", name="ck_push_delivery_jobs_attempt_count"
        ),
        Index(
            "ix_push_delivery_jobs_available_claimed",
            "available_at",
            "claimed_until",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    stale_cycle_id = Column(
        UUID(as_uuid=True),
        ForeignKey("stale_establishment_cycles.id", ondelete="CASCADE"),
        nullable=False,
    )
    device_id = Column(
        UUID(as_uuid=True),
        ForeignKey("user_push_devices.id", ondelete="CASCADE"),
        nullable=False,
    )
    threshold_hours = Column(SmallInteger, nullable=False)
    available_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    claimed_until = Column(DateTime(timezone=True), nullable=True)
    attempt_count = Column(Integer, default=0, server_default="0", nullable=False)

    stale_cycle = relationship(
        "StaleEstablishmentCycle", back_populates="delivery_jobs"
    )
    device = relationship("UserPushDevice", back_populates="delivery_jobs")
