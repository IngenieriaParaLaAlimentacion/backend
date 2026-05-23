import uuid

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    func,
    text,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from .base import Base
from .user import UserRole


class UserToken(Base):
    """Persisted refresh token bound to a user and device."""

    __tablename__ = "user_tokens"

    __table_args__ = (
        Index(
            "ix_user_tokens_token_hash_device_id_revoked",
            "token_hash",
            "device_id",
            "revoked",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    device_id = Column(UUID(as_uuid=True), nullable=False)
    role = Column(
        SAEnum(UserRole, values_callable=lambda x: [e.value for e in x]), nullable=False
    )
    token_hash = Column(String, nullable=False)
    expires_at = Column(
        DateTime(timezone=True),
        server_default=text("now() + interval '7 days'"),
        nullable=False,
    )
    revoked = Column(Boolean, default=False, nullable=False)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user = relationship("User", back_populates="tokens")
