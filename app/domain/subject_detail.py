"""Subject detail enriched with the subject's latest anthropometric reading.

Lives apart from ``app.domain.subject`` because ``app.domain.measurement``
already imports ``Sex`` from there; importing measurement types back into
subject.py would be circular.
"""

from dataclasses import dataclass

from app.domain.measurement import (
    MeasurementBase,
    MeasurementSummaryDomain,
    NutritionalStatus,
    SubjectRefDomain,
    status_from_alerts,
)
from app.domain.subject import SubjectDomain


@dataclass
class SubjectDetailDomain(SubjectDomain):
    """Full subject data plus the clinical reading of their latest measurement.

    ``latest_measurement`` is the subject's most recent reading at *any*
    establishment, unlike the establishment dashboard where it is scoped to a
    single one. Both extra fields are None for a subject that has never been
    measured. That is deliberately distinct from NORMAL, which means "measured
    and healthy".

    Also used to build the subject listing, which has no use for
    ``nutritional_status`` -- computing it is free once the measurement is
    loaded, and ``SubjectListingResponse`` simply doesn't declare the field,
    so it never reaches the client.
    """

    nutritional_status: NutritionalStatus | None
    latest_measurement: MeasurementSummaryDomain | None

    @classmethod
    def build(cls, subject, measurement) -> "SubjectDetailDomain":
        """Combine an ORM Subject with its latest ORM Measurement, if any."""
        base = vars(SubjectDomain.from_db(subject))
        if measurement is None:
            return cls(**base, nutritional_status=None, latest_measurement=None)
        return cls(
            **base,
            nutritional_status=status_from_alerts(measurement.alerts),
            latest_measurement=MeasurementSummaryDomain.from_db(measurement),
        )


@dataclass
class EvolutionPointDomain(MeasurementBase):
    """A single point in a subject's anthropometric evolution series."""


@dataclass
class SubjectEvolutionDomain:
    """A subject's full chronological anthropometric evolution."""

    subject: SubjectRefDomain
    points: list[EvolutionPointDomain]
