import uuid
from enum import Enum

from pydantic import BaseModel
from sqlalchemy import Column, DateTime, String, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from .base import Base


class UserRole(str, Enum):
    """Role that determines a user's permissions within the system."""

    ADMIN = "admin"
    PROFESSIONAL = "professional"
    ESTABLISHMENT_MANAGER = "establishment_manager"


class UserStatus(str, Enum):
    """Lifecycle state of a user account."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    PENDING_VALIDATION = "pending_validation"


class UserActor(BaseModel):
    user_id: uuid.UUID
    role: UserRole


class User(Base):
    """System user — professional, admin, or establishment manager."""

    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    last_name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False)
    role = Column(SAEnum(UserRole), nullable=False)
    status = Column(SAEnum(UserStatus), default=UserStatus.ACTIVE, nullable=False)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

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
