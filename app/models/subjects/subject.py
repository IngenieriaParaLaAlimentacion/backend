import uuid

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Integer,
    String,
    func,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.domain.subject import Sex

from ..base import Base


class Subject(Base):
    """Person whose anthropometric measurements are recorded."""

    __tablename__ = "subjects"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dni = Column(Integer, nullable=False, unique=True)
    sex = Column(
        SAEnum(Sex, values_callable=lambda x: [e.value for e in x]), nullable=False
    )
    name = Column(String, nullable=False)
    last_name = Column(String, nullable=False)
    birth_date = Column(Date, nullable=False)
    is_rural = Column(Boolean, default=False, nullable=False)
    is_indigenous = Column(Boolean, default=False, nullable=False)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    measurements = relationship(
        "Measurement",
        back_populates="subject",
        cascade="all, delete-orphan",
    )
