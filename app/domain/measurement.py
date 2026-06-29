from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum, StrEnum
from uuid import UUID

from app.domain.subject import Sex


class AlertType(str, Enum):
    SEVERELY_WASTED = "severely_wasted"
    WASTED = "wasted"
    OVERWEIGHT = "overweight"
    OBESE = "obese"
    SEVERE_UNDERWEIGHT = "severe_underweight"
    UNDERWEIGHT = "underweight"


class AlertSeverity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"


@dataclass
class AlertDomain:
    """A clinical alert generated from a single measurement."""

    id: UUID
    measurement_id: UUID
    alert_type: AlertType
    severity: AlertSeverity
    detail: str
    created_at: datetime

    @classmethod
    def from_db(cls, obj) -> "AlertDomain":
        """Build an AlertDomain from an ORM MeasurementAlert row."""
        return cls(
            id=obj.id,
            measurement_id=obj.measurement_id,
            alert_type=obj.alert_type,
            severity=obj.severity,
            detail=obj.detail,
            created_at=obj.created_at,
        )


@dataclass
class MeasurementDomain:
    """A registered anthropometric measurement with its clinical alerts."""

    id: UUID
    subject_id: UUID
    responsible_id: UUID
    establishment_id: UUID
    weight_kg: float
    height_cm: float
    bmi: float
    measured_at: datetime
    created_at: datetime
    alerts: list[AlertDomain]

    @classmethod
    def from_db(cls, obj) -> "MeasurementDomain":
        """Build an MeasurementDomain from ORM."""
        return cls(
            id=obj.id,
            subject_id=obj.subject_id,
            responsible_id=obj.responsible_id,
            establishment_id=obj.establishment_id,
            weight_kg=obj.weight_kg,
            height_cm=obj.height_cm,
            bmi=obj.bmi,
            measured_at=obj.measured_at,
            created_at=obj.created_at,
            alerts=[AlertDomain.from_db(a) for a in obj.alerts],
        )


class MeasurementSortOrder(StrEnum):
    """Sort orders accepted by the measurement listing."""

    DATE_DESC = "date_desc"
    DATE_ASC = "date_asc"
    WEIGHT_DESC = "weight_desc"
    WEIGHT_ASC = "weight_asc"
    HEIGHT_DESC = "height_desc"
    HEIGHT_ASC = "height_asc"


class EvolutionOrder(StrEnum):
    """Chronological order for a subject's anthropometric evolution series."""

    OLDEST_FIRST = "oldest_first"
    NEWEST_FIRST = "newest_first"


@dataclass
class MeasurementListingParams:
    """Query parameters for a paginated measurement listing."""

    subject_id: UUID | None = None
    establishment_id: UUID | None = None
    city: str | None = None
    province: str | None = None
    responsible_id: UUID | None = None
    measured_from: datetime | None = None
    measured_to: datetime | None = None
    min_age: int | None = None
    max_age: int | None = None
    sort_order: MeasurementSortOrder = MeasurementSortOrder.DATE_DESC

    def __post_init__(self) -> None:
        self.city = self.city.strip() or None if self.city else None
        self.province = self.province.strip() or None if self.province else None


@dataclass
class SubjectRefDomain:
    """Minimal subject reference embedded in a measurement listing item."""

    id: UUID
    dni: int
    sex: Sex
    name: str
    last_name: str
    birth_date: date

    @classmethod
    def from_db(cls, obj) -> "SubjectRefDomain":
        return cls(
            id=obj.id,
            dni=obj.dni,
            sex=obj.sex,
            name=obj.name,
            last_name=obj.last_name,
            birth_date=obj.birth_date,
        )


@dataclass
class EstablishmentRefDomain:
    """Minimal establishment reference embedded in a measurement listing item."""

    id: UUID
    name: str
    city: str
    province: str

    @classmethod
    def from_db(cls, obj) -> "EstablishmentRefDomain":
        return cls(id=obj.id, name=obj.name, city=obj.city, province=obj.province)


@dataclass
class ResponsibleRefDomain:
    """Minimal user reference for the responsible of a measurement."""

    id: UUID
    name: str
    last_name: str

    @classmethod
    def from_db(cls, obj) -> "ResponsibleRefDomain":
        return cls(id=obj.id, name=obj.name, last_name=obj.last_name)


@dataclass
class MeasurementListItemDomain:
    """An enriched measurement row for the listing view."""

    id: UUID
    measured_at: datetime
    weight_kg: float
    height_cm: float
    bmi: float
    subject: SubjectRefDomain
    establishment: EstablishmentRefDomain
    responsible: ResponsibleRefDomain
    alerts: list[AlertDomain]

    @classmethod
    def from_db(cls, obj) -> "MeasurementListItemDomain":
        """Build a listing item from an ORM Measurement with loaded relations."""
        return cls(
            id=obj.id,
            measured_at=obj.measured_at,
            weight_kg=obj.weight_kg,
            height_cm=obj.height_cm,
            bmi=obj.bmi,
            subject=SubjectRefDomain.from_db(obj.subject),
            establishment=EstablishmentRefDomain.from_db(obj.establishment),
            responsible=ResponsibleRefDomain.from_db(obj.responsible),
            alerts=[AlertDomain.from_db(a) for a in obj.alerts],
        )


@dataclass
class EvolutionPointDomain:
    """A single point in a subject's anthropometric evolution series."""

    measured_at: datetime
    weight_kg: float
    height_cm: float
    bmi: float
    alerts: list[AlertDomain]

    @classmethod
    def from_db(cls, obj) -> "EvolutionPointDomain":
        return cls(
            measured_at=obj.measured_at,
            weight_kg=obj.weight_kg,
            height_cm=obj.height_cm,
            bmi=obj.bmi,
            alerts=[AlertDomain.from_db(a) for a in obj.alerts],
        )


@dataclass
class SubjectEvolutionDomain:
    """A subject's full chronological anthropometric evolution."""

    subject: SubjectRefDomain
    points: list[EvolutionPointDomain]
