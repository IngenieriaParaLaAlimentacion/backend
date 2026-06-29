from datetime import date, datetime, timezone
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.measurement import AlertSeverity, AlertType
from app.domain.subject import Sex

# -- Request --


class MeasurementRequest(BaseModel):
    id: UUID | None = Field(
        default=None,
        description=(
            "Client-generated UUID for offline-first idempotency. When provided it "
            "becomes the measurement's primary key and repeated submissions with "
            "the same id are idempotent. When omitted, the server generates one."
        ),
    )
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


# -- Response --


class AlertResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    alert_type: AlertType
    severity: AlertSeverity
    detail: str


class MeasurementResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
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


class SubjectRefResponse(BaseModel):
    id: UUID
    dni: int
    sex: Sex
    name: str
    last_name: str
    birth_date: date

    model_config = {"from_attributes": True}


class EstablishmentRefResponse(BaseModel):
    id: UUID
    name: str
    city: str
    province: str

    model_config = {"from_attributes": True}


class ResponsibleRefResponse(BaseModel):
    id: UUID
    name: str
    last_name: str

    model_config = {"from_attributes": True}


class MeasurementListItem(BaseModel):
    id: UUID
    measured_at: datetime
    weight_kg: float
    height_cm: float
    bmi: float
    subject: SubjectRefResponse
    establishment: EstablishmentRefResponse
    responsible: ResponsibleRefResponse
    alerts: list[AlertResponse]

    model_config = {"from_attributes": True}


class EvolutionPoint(BaseModel):
    measured_at: datetime
    weight_kg: float
    height_cm: float
    bmi: float
    alerts: list[AlertResponse]

    model_config = {"from_attributes": True}


class SubjectEvolutionResponse(BaseModel):
    subject: SubjectRefResponse
    points: list[EvolutionPoint]

    model_config = {"from_attributes": True}
