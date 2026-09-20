import uuid

from sqlalchemy import Column, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.domain.notifications import PushPlatform
from app.models.base import Base


class UserPushDevice(Base):
    """One current FCM registration for a physical app installation."""

    __tablename__ = "user_push_devices"
    __table_args__ = (
        UniqueConstraint(
            "installation_id", name="uq_user_push_devices_installation_id"
        ),
        UniqueConstraint("fcm_token", name="uq_user_push_devices_fcm_token"),
        Index("ix_user_push_devices_user_id", "user_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    installation_id = Column(String(255), nullable=False)
    fcm_token = Column(Text, nullable=False)
    platform = Column(
        SAEnum(
            PushPlatform,
            name="pushplatform",
            values_callable=lambda enum: [item.value for item in enum],
        ),
        nullable=False,
    )
    device_name = Column(String(255), nullable=True)
    user = relationship("User", back_populates="push_devices")
    delivery_jobs = relationship(
        "PushDeliveryJob",
        back_populates="device",
        passive_deletes=True,
    )
