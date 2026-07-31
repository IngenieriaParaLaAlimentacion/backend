"""Subject detail enriched with the subject's latest anthropometric reading.

Lives apart from ``app.domain.subject`` because ``app.domain.measurement``
already imports ``Sex`` from there; importing measurement types back into
subject.py would be circular.
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.domain.measurement import (
    AlertDomain,
    EstablishmentRefDomain,
    NutritionalStatus,
    status_from_alerts,
)
from app.domain.subject import SubjectDomain


@dataclass
class SubjectLatestMeasurementDomain:
    """A subject's most recent measurement, taken at any establishment."""

    id: UUID
    measured_at: datetime
    weight_kg: float
    height_cm: float
    bmi: float
    establishment: EstablishmentRefDomain
    alerts: list[AlertDomain]

    @classmethod
    def from_db(cls, obj) -> "SubjectLatestMeasurementDomain":
        """Build from an ORM Measurement with establishment and alerts loaded."""
        return cls(
            id=obj.id,
            measured_at=obj.measured_at,
            weight_kg=obj.weight_kg,
            height_cm=obj.height_cm,
            bmi=obj.bmi,
            establishment=EstablishmentRefDomain.from_db(obj.establishment),
            alerts=[AlertDomain.from_db(a) for a in obj.alerts],
        )


@dataclass
class SubjectDetailDomain(SubjectDomain):
    """Full subject data plus the clinical reading of their latest measurement.

    Both extra fields are None for a subject that has never been measured. That
    is deliberately distinct from NORMAL, which means "measured and healthy".
    """

    nutritional_status: NutritionalStatus | None
    latest_measurement: SubjectLatestMeasurementDomain | None

    @classmethod
    def build(cls, subject, measurement) -> "SubjectDetailDomain":
        """Combine an ORM Subject with its latest ORM Measurement, if any."""
        base = vars(SubjectDomain.from_db(subject))
        if measurement is None:
            return cls(**base, nutritional_status=None, latest_measurement=None)
        return cls(
            **base,
            nutritional_status=status_from_alerts(measurement.alerts),
            latest_measurement=SubjectLatestMeasurementDomain.from_db(measurement),
        )
