from datetime import date, datetime
from typing import Annotated
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PlainSerializer,
    field_validator,
)

from app.domain.measurement import AlertSeverity, AlertType
from app.domain.subject import Sex
from app.schemas.common import IdentifierRefSchema
from app.utils.dates import is_future_date

# BMI carries full precision in storage and alert computation; it is rounded to
# two decimals only when serialized for API responses.
RoundedBmi = Annotated[float, PlainSerializer(lambda v: round(v, 2), return_type=float)]

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
        if is_future_date(v):
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
    bmi: RoundedBmi
    measured_at: datetime
    created_at: datetime
    alerts: list[AlertResponse]


class SubjectRefResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    dni: int
    sex: Sex
    name: str
    last_name: str
    birth_date: date


class EstablishmentRefResponse(IdentifierRefSchema):
    city: str
    province: str


class ResponsibleRefResponse(IdentifierRefSchema):
    last_name: str


class MeasurementListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    measured_at: datetime
    weight_kg: float
    height_cm: float
    bmi: RoundedBmi
    subject: SubjectRefResponse
    establishment: EstablishmentRefResponse
    responsible: ResponsibleRefResponse
    alerts: list[AlertResponse]


class EvolutionPoint(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    measured_at: datetime
    weight_kg: float
    height_cm: float
    bmi: RoundedBmi
    alerts: list[AlertResponse]


class SubjectEvolutionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    subject: SubjectRefResponse
    points: list[EvolutionPoint]
