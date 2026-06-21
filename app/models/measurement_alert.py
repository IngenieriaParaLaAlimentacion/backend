import uuid

from sqlalchemy import Column, DateTime, ForeignKey, String, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.domain.measurement import AlertSeverity, AlertType

from .base import Base


class MeasurementAlert(Base):
    """Clinical alert generated when a measurement indicates nutritional risk."""

    __tablename__ = "measurement_alerts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    measurement_id = Column(
        UUID(as_uuid=True),
        ForeignKey("measurements.id", ondelete="CASCADE"),
        nullable=False,
    )
    alert_type = Column(
        SAEnum(AlertType, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    severity = Column(
        SAEnum(AlertSeverity, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    detail = Column(String, nullable=False)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    measurement = relationship("Measurement", back_populates="alerts")
