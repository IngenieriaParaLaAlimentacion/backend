from sqlalchemy import Column, ForeignKey
from sqlalchemy.dialects.postgresql import UUID

from .base import Base


class SurveyEstablishment(Base):
    """Association table targeting a survey at specific establishments."""

    __tablename__ = "survey_establishments"

    survey_id = Column(
        UUID(as_uuid=True),
        ForeignKey("surveys.id", ondelete="CASCADE"),
        primary_key=True,
    )
    establishment_id = Column(
        UUID(as_uuid=True),
        ForeignKey("establishments.id", ondelete="CASCADE"),
        primary_key=True,
    )
