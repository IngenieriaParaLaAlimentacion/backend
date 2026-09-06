from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.domain.establishment import UserEstablishmentStatus
from app.domain.measurement import AlertSeverity, NutritionalStatus
from app.domain.subject import Sex
from app.domain.user import UserStatus
from app.schemas.establishments.establishment_schema import EstablishmentResponse
from app.schemas.measurements.measurement_schema import (
    MeasurementSnapshotBase,
)
from app.schemas.types import RoundedNullableFloat

# -- Response --


class EstablishmentMetricsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    subject_count: int
    measurement_count: int
    last_measured_at: datetime | None
    avg_height_cm: RoundedNullableFloat
    avg_weight_kg: RoundedNullableFloat
    avg_bmi: RoundedNullableFloat
    avg_age_months: int | None


class StatusDistributionEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    status: NutritionalStatus
    severity: AlertSeverity | None
    count: int
    percentage: float


class EstablishmentAlertStatusResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    severity: AlertSeverity | None
    dominant_status: NutritionalStatus | None
    total_evaluated: int
    at_risk_count: int
    at_risk_percentage: float | None
    distribution: list[StatusDistributionEntryResponse]


class EstablishmentDashboardResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    establishment: EstablishmentResponse
    has_data: bool
    metrics: EstablishmentMetricsResponse
    alert_status: EstablishmentAlertStatusResponse


class LatestMeasurementResponse(MeasurementSnapshotBase):
    """The subject's latest reading at the establishment being viewed."""

    id: UUID


class EstablishmentSubjectListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    dni: int
    name: str
    last_name: str
    sex: Sex
    birth_date: date
    age_months: int
    measurement_count: int
    nutritional_status: NutritionalStatus
    latest_measurement: LatestMeasurementResponse


class EstablishmentFieldWorkerListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    last_name: str
    email: str
    user_status: UserStatus
    relation_status: UserEstablishmentStatus
    measurement_count: int
    last_measured_at: datetime | None
