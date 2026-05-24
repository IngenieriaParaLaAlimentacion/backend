import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from .base import Base


class PasswordRecoveryToken(Base):
    """Persisted one-time token metadata for password recovery."""

    __tablename__ = "password_recovery_tokens"
    __table_args__ = (
        Index("ix_password_recovery_tokens_user_id_used", "user_id", "used"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    token_hash = Column(String, nullable=False, unique=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False)

    user = relationship("User", back_populates="password_recovery_tokens")
