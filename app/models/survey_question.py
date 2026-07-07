import uuid

from sqlalchemy import Boolean, Column, ForeignKey, Integer, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.domain.survey import ResponseType

from .base import Base


class SurveyQuestion(Base):
    """A single question belonging to a survey."""

    __tablename__ = "survey_questions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    survey_id = Column(
        UUID(as_uuid=True),
        ForeignKey("surveys.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    text = Column(String, nullable=False)
    response_type = Column(
        SAEnum(ResponseType, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    is_required = Column(Boolean, nullable=False)
    position = Column(Integer, nullable=False)

    survey = relationship("Survey", back_populates="questions")
    options = relationship(
        "SurveyQuestionOption",
        back_populates="question",
        cascade="all, delete-orphan",
        order_by="SurveyQuestionOption.position",
        lazy="selectin",
    )
