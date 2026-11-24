from collections import defaultdict
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import delete, exists, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.measurement import AlertSeverity
from app.domain.measurement_assessment import (
    Assessment,
    AssessmentAlert,
    AssessmentStatus,
    Indicator,
)
from app.models.measurements.measurement import Measurement
from app.models.measurements.measurement_assessment import MeasurementAssessment
from app.models.subjects.subject import Subject


def assessment_from_row(row: MeasurementAssessment) -> Assessment:
    """Convert a persisted assessment to a domain result."""
    return Assessment(
        indicator=Indicator(row.indicator),
        status=AssessmentStatus(row.status),
        classification=row.classification,
        z_score=row.z_score,
        reference_version=row.reference_version,
        alert=(
            AssessmentAlert(AlertSeverity(row.alert_severity), row.alert_detail)
            if row.alert_severity is not None
            else None
        ),
    )


def evaluated_assessment(
    measurement_id,
    *,
    ruleset_version: str,
    indicator: Indicator,
    classification: str | None = None,
):
    """Match an evaluated indicator on the specified measurement."""
    conditions = [
        MeasurementAssessment.measurement_id == measurement_id,
        MeasurementAssessment.ruleset_version == ruleset_version,
        MeasurementAssessment.indicator == indicator,
        MeasurementAssessment.status == AssessmentStatus.EVALUATED,
    ]
    if classification is not None:
        conditions.append(MeasurementAssessment.classification == classification)
    return exists(select(1).where(*conditions))


def _missing_assessment(ruleset_version: str):
    return select(func.count()).select_from(MeasurementAssessment).where(
        MeasurementAssessment.measurement_id == Measurement.id,
        MeasurementAssessment.ruleset_version == ruleset_version,
    ).correlate(Measurement).scalar_subquery() < len(Indicator)


class MeasurementAssessmentRepository:
    """Persist and retrieve results for a specific ruleset."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def invalidate_other_versions(
        self, measurement_ids: Sequence[UUID], keep_version: str | None
    ) -> None:
        """Remove results based on measurement inputs that have changed."""
        if not measurement_ids:
            return
        stmt = delete(MeasurementAssessment).where(
            MeasurementAssessment.measurement_id.in_(measurement_ids)
        )
        if keep_version is not None:
            stmt = stmt.where(MeasurementAssessment.ruleset_version != keep_version)
        await self.db.execute(stmt)

    async def upsert(
        self,
        measurement_id: UUID,
        ruleset_version: str,
        assessments: Sequence[Assessment],
    ) -> None:
        """Store the supplied outcomes in the current transaction."""
        values = [
            {
                "measurement_id": measurement_id,
                "ruleset_version": ruleset_version,
                "indicator": result.indicator,
                "status": result.status,
                "classification": result.classification,
                "z_score": result.z_score,
                "reference_version": result.reference_version,
                "alert_severity": result.alert.severity if result.alert else None,
                "alert_detail": result.alert.detail if result.alert else None,
            }
            for result in assessments
        ]
        stmt = insert(MeasurementAssessment).values(values)
        await self.db.execute(
            stmt.on_conflict_do_update(
                constraint="pk_measurement_assessments",
                set_={
                    name: stmt.excluded[name]
                    for name in (
                        "status",
                        "classification",
                        "z_score",
                        "reference_version",
                        "alert_severity",
                        "alert_detail",
                    )
                },
            )
        )

    async def list_for_measurements(
        self, ids: Sequence[UUID], version: str
    ) -> dict[UUID, tuple[Assessment, ...]]:
        """Load results for a batch of measurements at one version."""
        if not ids:
            return {}
        stmt = select(MeasurementAssessment).where(
            MeasurementAssessment.measurement_id.in_(ids),
            MeasurementAssessment.ruleset_version == version,
        )
        by_id = defaultdict(dict)
        for row in (await self.db.scalars(stmt)).all():
            result = assessment_from_row(row)
            by_id[row.measurement_id][result.indicator] = result
        return {
            measurement_id: tuple(results[key] for key in Indicator if key in results)
            for measurement_id, results in by_id.items()
        }

    async def count_missing(self, version: str) -> int:
        """Count measurements without a complete evaluation for this version."""
        stmt = (
            select(func.count())
            .select_from(Measurement)
            .where(_missing_assessment(version))
        )
        return (await self.db.execute(stmt)).scalar_one()

    async def list_subjects_missing(
        self, version: str, after: UUID | None, limit: int
    ) -> Sequence[UUID]:
        """Page through subjects with at least one incomplete measurement."""
        missing = exists(
            select(1)
            .select_from(Measurement)
            .where(
                Measurement.subject_id == Subject.id,
                _missing_assessment(version),
            )
        )
        stmt = select(Subject.id).where(missing).order_by(Subject.id).limit(limit)
        if after is not None:
            stmt = stmt.where(Subject.id > after)
        return (await self.db.scalars(stmt)).all()

    async def list_missing_for_subject(
        self, version: str, subject_id: UUID
    ) -> Sequence[Measurement]:
        """List measurements to evaluate after locking their subject."""
        stmt = (
            select(Measurement)
            .where(
                Measurement.subject_id == subject_id,
                _missing_assessment(version),
            )
            .order_by(Measurement.id)
        )
        return (await self.db.scalars(stmt)).all()
