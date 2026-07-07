import uuid

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    func,
    true,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.domain.survey import SurveyScope

from .base import Base


class Survey(Base):
    """A configurable survey authored from the backoffice (Module 2)."""

    __tablename__ = "surveys"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    scope = Column(
        SAEnum(SurveyScope, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    created_by_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    is_active = Column(Boolean, nullable=False, server_default=true())
    # STUB: response collection is out of scope; always 0 until that ticket lands.
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
