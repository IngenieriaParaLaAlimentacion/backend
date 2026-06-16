from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from uuid import UUID


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
    idempotency_key: UUID
    subject_id: UUID
    responsible_id: UUID
    establishment_id: UUID
    weight_kg: float
    height_cm: float
    bmi: float
    measured_at: datetime
    created_at: datetime
    alerts: list[AlertDomain]
