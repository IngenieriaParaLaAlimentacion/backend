from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from uuid import UUID

from app.domain.establishment import EstablishmentDomain, UserEstablishmentStatus
from app.domain.measurement import (
    AlertSeverity,
    MeasurementSummaryDomain,
    NutritionalStatus,
)
from app.domain.subject import Sex
from app.domain.user import UserStatus


class EstablishmentSubjectSortOrder(StrEnum):
    """Sort orders accepted by the per-establishment subject listing."""

    MEASURED_AT_DESC = "measured_at_desc"
    MEASURED_AT_ASC = "measured_at_asc"
    NAME_ASC = "name_asc"
    NAME_DESC = "name_desc"
    BMI_DESC = "bmi_desc"
    BMI_ASC = "bmi_asc"
    AGE_DESC = "age_desc"
    AGE_ASC = "age_asc"


@dataclass
class EstablishmentSubjectListingParams:
    """Query parameters for the per-establishment subject listing."""

    search: str | None = None
    sort_order: EstablishmentSubjectSortOrder = (
        EstablishmentSubjectSortOrder.MEASURED_AT_DESC
    )

    def __post_init__(self) -> None:
        self.search = self.search.strip() or None if self.search else None


@dataclass
class EstablishmentFieldWorkerListingParams:
    """Query parameters for the per-establishment field worker listing."""

    search: str | None = None
    relation_status: UserEstablishmentStatus = UserEstablishmentStatus.APPROVED

    def __post_init__(self) -> None:
        self.search = self.search.strip() or None if self.search else None


@dataclass
class EstablishmentMetricsDomain:
    """Aggregated anthropometric metrics for a single establishment.

    Averages are computed over one row per subject -- their most recent
    measurement at this establishment -- so subjects measured many times do not
    skew the result. All averages are None when the establishment has no
    measurements, never zero.
    """

    subject_count: int
    measurement_count: int
    last_measured_at: datetime | None
    avg_height_cm: float | None
    avg_weight_kg: float | None
    avg_bmi: float | None
    avg_age_months: int | None

    @classmethod
    def empty(cls) -> "EstablishmentMetricsDomain":
        """Return the metrics of an establishment with no measurements."""
        return cls(
            subject_count=0,
            measurement_count=0,
            last_measured_at=None,
            avg_height_cm=None,
            avg_weight_kg=None,
            avg_bmi=None,
            avg_age_months=None,
        )


@dataclass
class StatusDistributionEntryDomain:
    """How many subjects fall into one nutritional status."""

    status: NutritionalStatus
    severity: AlertSeverity | None
    count: int
    percentage: float


@dataclass
class EstablishmentAlertStatusDomain:
    """Establishment-wide alert state rolled up from individual subject states."""

    severity: AlertSeverity | None
    dominant_status: NutritionalStatus | None
    total_evaluated: int
    at_risk_count: int
    at_risk_percentage: float | None
    distribution: list[StatusDistributionEntryDomain]

    @classmethod
    def empty(cls) -> "EstablishmentAlertStatusDomain":
        """Return the alert state of an establishment with no measured subjects."""
        return cls(
            severity=None,
            dominant_status=None,
            total_evaluated=0,
            at_risk_count=0,
            at_risk_percentage=None,
            distribution=[],
        )


@dataclass
class EstablishmentDashboardDomain:
    """Full dashboard payload for one establishment."""

    establishment: EstablishmentDomain
    has_data: bool
    metrics: EstablishmentMetricsDomain
    alert_status: EstablishmentAlertStatusDomain


@dataclass
class EstablishmentSubjectItemDomain:
    """A subject attending an establishment, enriched with their latest data."""

    id: UUID
    dni: int
    name: str
    last_name: str
    sex: Sex
    birth_date: date
    age_months: int
    measurement_count: int
    nutritional_status: NutritionalStatus
    # Latest measurement AT THIS establishment
    latest_measurement: MeasurementSummaryDomain


@dataclass
class EstablishmentFieldWorkerItemDomain:
    """A field worker enrolled in an establishment, with their activity there."""

    id: UUID
    name: str
    last_name: str
    email: str
    user_status: UserStatus
    relation_status: UserEstablishmentStatus
    measurement_count: int
    last_measured_at: datetime | None
