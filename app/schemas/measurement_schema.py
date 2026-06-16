from datetime import datetime, timezone
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.domain.measurement import AlertSeverity, AlertType


class MeasurementRequest(BaseModel):
    subject_id: UUID
    establishment_id: UUID
    weight_kg: float = Field(gt=0.5, le=300, description="Weight in kilograms.")
    height_cm: float = Field(gt=20.0, le=250.0, description="Height in centimetres.")
    measured_at: datetime

    @field_validator("measured_at")
    @classmethod
    def measured_at_not_future(cls, v: datetime) -> datetime:
        if v > datetime.now(timezone.utc):
            raise ValueError("measured_at cannot be in the future")
        return v


class AlertResponse(BaseModel):
    alert_type: AlertType
    severity: AlertSeverity
    detail: str

    model_config = {"from_attributes": True}


class MeasurementResponse(BaseModel):
    id: UUID
    idempotency_key: UUID
    subject_id: UUID
    responsible_id: UUID
    establishment_id: UUID
    weight_kg: float
    height_cm: float
    bmi: float
    measured_at: datetime
    created_at: datetime
    alerts: list[AlertResponse]

    model_config = {"from_attributes": True}
