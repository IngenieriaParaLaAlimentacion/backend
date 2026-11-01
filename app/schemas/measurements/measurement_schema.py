from datetime import date, datetime
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)

from app.domain.common_domains import normalize_optional_str
from app.domain.measurement import AlertSeverity, AlertType
from app.domain.subject import Sex
from app.schemas.common import IdentifierRefSchema
from app.schemas.types import ClientGeneratedId, RoundedBmi
from app.utils.dates import validate_not_future_datetime

# -- Request --


class MeasurementRequest(BaseModel):
    id: ClientGeneratedId
    subject_id: UUID
    establishment_id: UUID
    weight_kg: float = Field(gt=0.5, le=300, description="Weight in kilograms.")
    height_cm: float = Field(gt=20.0, le=250.0, description="Height in centimetres.")
    measured_at: datetime
    observation: str | None = Field(default=None, max_length=500)

    @field_validator("observation", mode="before")
    @classmethod
    def normalize_observation(cls, value):
        """Trim optional observation text and collapse blank input."""
        return normalize_optional_str(value) if isinstance(value, str) else value

    _check_measured_at = field_validator("measured_at")(validate_not_future_datetime)


# -- Response --


class AlertResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    alert_type: AlertType
    severity: AlertSeverity
    detail: str


class MeasurementSnapshotBase(BaseModel):
    """A clinical reading of a measurement, shared by snapshots."""

    model_config = ConfigDict(from_attributes=True)

    measured_at: datetime
    weight_kg: float
    height_cm: float
    bmi: RoundedBmi
    alerts: list[AlertResponse]
    observation: str | None = None


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
    observation: str | None = None


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
    observation: str | None = None


class EvolutionPoint(MeasurementSnapshotBase):
    pass


class SubjectEvolutionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    subject: SubjectRefResponse
    points: list[EvolutionPoint]
