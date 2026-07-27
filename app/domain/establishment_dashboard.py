from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from uuid import UUID

from app.domain.establishment import EstablishmentDomain, UserEstablishmentStatus
from app.domain.measurement import AlertDomain, AlertSeverity, AlertType
from app.domain.subject import Sex
from app.domain.user import UserStatus


class NutritionalStatus(StrEnum):
    """Nutritional classification derived from a subject's latest measurement."""

    NORMAL = "normal"
    OVERWEIGHT = "overweight"
    OBESE = "obese"
    WASTED = "wasted"
    SEVERELY_WASTED = "severely_wasted"
    UNDERWEIGHT = "underweight"
    SEVERE_UNDERWEIGHT = "severe_underweight"


# ``evaluate_alerts`` emits at most one alert per measurement, so an alert type
# maps one-to-one onto a nutritional status and "no alert" means NORMAL. If a
# measurement ever carried several alerts, the service would have to collapse
# them by picking the worst severity before using this mapping.
ALERT_TO_STATUS: dict[AlertType, NutritionalStatus] = {
    AlertType.SEVERELY_WASTED: NutritionalStatus.SEVERELY_WASTED,
    AlertType.WASTED: NutritionalStatus.WASTED,
    AlertType.OVERWEIGHT: NutritionalStatus.OVERWEIGHT,
    AlertType.OBESE: NutritionalStatus.OBESE,
    AlertType.SEVERE_UNDERWEIGHT: NutritionalStatus.SEVERE_UNDERWEIGHT,
    AlertType.UNDERWEIGHT: NutritionalStatus.UNDERWEIGHT,
}

STATUS_TO_SEVERITY: dict[NutritionalStatus, AlertSeverity | None] = {
    NutritionalStatus.NORMAL: None,
    NutritionalStatus.OVERWEIGHT: AlertSeverity.MEDIUM,
    NutritionalStatus.OBESE: AlertSeverity.HIGH,
    NutritionalStatus.WASTED: AlertSeverity.HIGH,
    NutritionalStatus.SEVERELY_WASTED: AlertSeverity.CRITICAL,
    NutritionalStatus.UNDERWEIGHT: AlertSeverity.HIGH,
    NutritionalStatus.SEVERE_UNDERWEIGHT: AlertSeverity.CRITICAL,
}

# Ranks severities so the service can pick the worst one present. Higher wins.
SEVERITY_RANK: dict[AlertSeverity | None, int] = {
    None: 0,
    AlertSeverity.MEDIUM: 1,
    AlertSeverity.HIGH: 2,
    AlertSeverity.CRITICAL: 3,
}


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
class LatestMeasurementDomain:
    """A subject's most recent measurement at a given establishment."""

    id: UUID
    measured_at: datetime
    weight_kg: float
    height_cm: float
    bmi: float
    alerts: list[AlertDomain]

    @classmethod
    def from_db(cls, obj) -> "LatestMeasurementDomain":
        """Build from an ORM Measurement with its alerts loaded."""
        return cls(
            id=obj.id,
            measured_at=obj.measured_at,
            weight_kg=obj.weight_kg,
            height_cm=obj.height_cm,
            bmi=obj.bmi,
            alerts=[AlertDomain.from_db(a) for a in obj.alerts],
        )


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
    latest_measurement: LatestMeasurementDomain


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
