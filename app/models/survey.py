import uuid

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
    text,
    true,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.domain.survey import SurveyInstrumentType, SurveyScope

from .base import Base


class Survey(Base):
    """A configurable survey authored from the backoffice (Module 2)."""

    __tablename__ = "surveys"
    __table_args__ = (
        # Case-insensitive uniqueness; see uq_surveys_lower_name in the Alembic
        # migration that created this table.
        Index("uq_surveys_lower_name", text("lower(name)"), unique=True),
        Index("ix_surveys_created_by_id", "created_by_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    scope = Column(
        SAEnum(SurveyScope, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    instrument_type = Column(
        SAEnum(SurveyInstrumentType, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        server_default="custom",
    )
    created_by_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    is_active = Column(Boolean, nullable=False, server_default=true())
    response_count = Column(Integer, nullable=False, server_default="0")
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    questions = relationship(
        "SurveyQuestion",
        back_populates="survey",
        cascade="all, delete-orphan",
        order_by="SurveyQuestion.position",
        lazy="selectin",
    )
    establishments = relationship(
        "Establishment",
        secondary="survey_establishments",
        lazy="selectin",
    )
