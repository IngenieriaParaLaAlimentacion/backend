import uuid

from sqlalchemy import Column, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from ..base import Base


class SurveyQuestionOption(Base):
    """A choice option belonging to a survey question."""

    __tablename__ = "survey_question_options"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    question_id = Column(
        UUID(as_uuid=True),
        ForeignKey("survey_questions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    text = Column(String, nullable=False)
    position = Column(Integer, nullable=False)

    question = relationship("SurveyQuestion", back_populates="options")
