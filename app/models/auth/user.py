import uuid

from sqlalchemy import Boolean, Column, DateTime, String, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.domain.user import UserRole, UserStatus

from ..base import Base


class User(Base):
    """System user — analyst, admin, or field worker."""

    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    last_name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False)
    role = Column(
        SAEnum(UserRole, values_callable=lambda x: [e.value for e in x]), nullable=False
    )
    status = Column(
        SAEnum(UserStatus, values_callable=lambda x: [e.value for e in x]),
        default=UserStatus.PENDING_VALIDATION,
        nullable=False,
    )
    is_email_verified = Column(Boolean, default=False, nullable=False)
    email_verified_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    locality = Column(String, nullable=True)
    description = Column(String, nullable=True)
    contact_phone = Column(String, nullable=True)

    password = relationship(
        "UserPassword",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )
    tokens = relationship(
        "UserToken",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    establishments = relationship(
        "Establishment",
        secondary="user_establishments",
        back_populates="users",
    )
    measurements = relationship(
        "Measurement",
        back_populates="responsible",
        foreign_keys="[Measurement.responsible_id]",
    )
    food_intakes = relationship(
        "FoodIntake",
        back_populates="responsible",
        foreign_keys="[FoodIntake.responsible_id]",
    )
    recovery_tokens = relationship(
        "PasswordRecoveryToken",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    email_verification_tokens = relationship(
        "EmailVerificationToken",
        back_populates="user",
        cascade="all, delete-orphan",
    )
