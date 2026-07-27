from datetime import date, datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, PlainSerializer

from app.domain.establishment import UserEstablishmentStatus
from app.domain.establishment_dashboard import NutritionalStatus
from app.domain.measurement import AlertSeverity
from app.domain.subject import Sex
from app.domain.user import UserStatus
from app.schemas.establishment_schema import EstablishmentResponse
from app.schemas.measurement_schema import AlertResponse, RoundedBmi

# Averages are absent (not zero) for an establishment with no data, so unlike
# ``RoundedBmi`` this serializer has to survive None.
RoundedAverage = Annotated[
    float | None,
    PlainSerializer(
        lambda v: None if v is None else round(v, 2), return_type=float | None
    ),
]

# -- Response --


class EstablishmentMetricsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    subject_count: int
    measurement_count: int
    last_measured_at: datetime | None
    avg_height_cm: RoundedAverage
    avg_weight_kg: RoundedAverage
    avg_bmi: RoundedAverage
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


class LatestMeasurementResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    measured_at: datetime
    weight_kg: float
    height_cm: float
    bmi: RoundedBmi
    alerts: list[AlertResponse]


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
