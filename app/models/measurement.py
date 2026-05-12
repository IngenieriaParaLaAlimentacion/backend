import uuid

from sqlalchemy import Column, DateTime, Float, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from .base import Base


class Measurement(Base):
    """Single anthropometric measurement session for a subject."""

    __tablename__ = "measurements"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    subject_id = Column(
        UUID(as_uuid=True),
        ForeignKey("subjects.id", ondelete="CASCADE"),
        nullable=False,
    )
    responsible_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    establishment_id = Column(
        UUID(as_uuid=True),
        ForeignKey("establishments.id", ondelete="RESTRICT"),
        nullable=False,
    )
    weight_kg = Column(Float, nullable=False)
    height_cm = Column(Float, nullable=False)
    measured_at = Column(DateTime(timezone=True), nullable=False)
    synced_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    subject = relationship("Subject", back_populates="measurements")
    responsible = relationship(
        "User",
        foreign_keys="[Measurement.responsible_id]",
        back_populates="measurements",
    )
    establishment = relationship("Establishment", back_populates="measurements")
