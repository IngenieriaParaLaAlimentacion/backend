from collections.abc import AsyncIterator
from datetime import date, datetime
from uuid import UUID

from sqlalchemy import asc, desc, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.domain.measurement import (
    EvolutionOrder,
    MeasurementListingParams,
)
from app.domain.measurement_assessment import Assessment, Indicator
from app.exceptions.domain_exceptions import UniqueConstraintError
from app.models.establishments.establishment import Establishment
from app.models.measurements.measurement import Measurement
from app.models.measurements.measurement_assessment import MeasurementAssessment
from app.models.subjects.subject import Subject
from app.repositories.measurements.constants import MEASUREMENT_SORT_CLAUSES
from app.repositories.measurements.measurement_assessment_repository import (
    assessment_from_row,
    evaluated_assessment,
)
from app.utils.db import (
    execute_count,
    execute_paginated,
    ilike_condition,
    stream_all,
)


def _subtract_years(reference: date, years: int) -> date:
    """Return ``reference`` shifted back by ``years``, clamping Feb 29 to Feb 28."""
    try:
        return reference.replace(year=reference.year - years)
    except ValueError:
        # reference is Feb 29 and the target year is not a leap year.
        return reference.replace(year=reference.year - years, day=28)


class MeasurementRepository:
    """Persistence operations for Measurement entities."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, measurement_id: UUID) -> Measurement | None:
        """Return a measurement by id, or None if it does not exist."""
        return await self.db.get(Measurement, measurement_id)

    async def get_by_id_with_assessments(
        self, measurement_id: UUID, ruleset_version: str
    ) -> tuple[Measurement, tuple[Assessment, ...] | None] | None:
        """Load the raw values, legacy alerts, and active assessments together."""
        result = await self.db.execute(
            select(Measurement)
            .where(Measurement.id == measurement_id)
            .options(
                joinedload(Measurement.alerts),
                joinedload(
                    Measurement.assessments.and_(
                        MeasurementAssessment.ruleset_version == ruleset_version
                    )
                ),
            )
            .execution_options(populate_existing=True)
        )
        measurement = result.unique().scalar_one_or_none()
        if measurement is None:
            return None
        assessments = {
            row.indicator: assessment_from_row(row) for row in measurement.assessments
        }
        return measurement, (
            tuple(assessments[key] for key in Indicator if key in assessments)
            if assessments
            else None
        )

    async def get_current_by_id(self, measurement_id: UUID) -> Measurement | None:
        """Refresh the measurement after acquiring its subject lock."""
        return await self.db.get(Measurement, measurement_id, populate_existing=True)

    async def update(self, measurement: Measurement, fields: dict) -> Measurement:
        """Flush the corrected measurement values."""
        for key, value in fields.items():
            setattr(measurement, key, value)
        await self.db.flush()
        return measurement

    async def list_for_subject(self, subject_id: UUID) -> list[Measurement]:
        """Return a subject's measurements in stable ID order."""
        result = await self.db.scalars(
            select(Measurement)
            .where(Measurement.subject_id == subject_id)
            .order_by(Measurement.id)
        )
        return list(result.all())

    @staticmethod
    def _listing_conditions(params: MeasurementListingParams) -> list:
        """Build the filter conditions for a measurement listing."""
        conditions = []
        if params.subject_id is not None:
            conditions.append(Measurement.subject_id == params.subject_id)
        if params.establishment_id is not None:
            conditions.append(Measurement.establishment_id == params.establishment_id)
        if params.responsible_id is not None:
            conditions.append(Measurement.responsible_id == params.responsible_id)
        if params.city:
            conditions.append(ilike_condition(Establishment.city, params.city))
        if params.province:
            conditions.append(ilike_condition(Establishment.province, params.province))
        if params.measured_from is not None:
            conditions.append(Measurement.measured_at >= params.measured_from)
        if params.measured_to is not None:
            conditions.append(Measurement.measured_at <= params.measured_to)
        # Age filter -> birth_date bounds (current age as of today).
        if params.min_age is not None:
            conditions.append(
                Subject.birth_date <= _subtract_years(date.today(), params.min_age)
            )
        if params.max_age is not None:
            conditions.append(
                Subject.birth_date > _subtract_years(date.today(), params.max_age + 1)
            )
        if params.indicator is not None and params.ruleset_version is not None:
            conditions.append(
                evaluated_assessment(
                    Measurement.id,
                    ruleset_version=params.ruleset_version,
                    indicator=params.indicator,
                    classification=params.classification,
                )
            )
        return conditions

    @staticmethod
    def _listing_base_query():
        """Build the listing's entity query, joined and eager-loaded.

        Joins Subject and Establishment to support filtering by establishment
        location and subject age. The eager loads keep the listing and the
        export off an N+1 when their rows are mapped to domain objects.
        """
        return (
            select(Measurement)
            .join(Subject, Measurement.subject_id == Subject.id)
            .join(Establishment, Measurement.establishment_id == Establishment.id)
            .options(
                selectinload(Measurement.subject),
                selectinload(Measurement.establishment),
                selectinload(Measurement.responsible),
            )
        )

    async def get_measurement_listing(
        self,
        limit: int,
        offset: int,
        params: MeasurementListingParams,
    ) -> tuple[list[Measurement], int]:
        """Return a paginated list of measurements and the total matching count.

        City and province are case-insensitive partial matches on the joined
        establishment.
        """
        count_query = (
            select(func.count())
            .select_from(Measurement)
            .join(Subject, Measurement.subject_id == Subject.id)
            .join(Establishment, Measurement.establishment_id == Establishment.id)
        )

        order_by = MEASUREMENT_SORT_CLAUSES[params.sort_order]
        return await execute_paginated(
            self.db,
            self._listing_base_query(),
            count_query,
            order_by,
            limit,
            offset,
            conditions=self._listing_conditions(params),
        )

    @staticmethod
    def _listing_count_query():
        """Count over the same joins the listing query uses."""
        return (
            select(func.count())
            .select_from(Measurement)
            .join(Subject, Measurement.subject_id == Subject.id)
            .join(Establishment, Measurement.establishment_id == Establishment.id)
        )

    def stream_for_export(
        self, params: MeasurementListingParams
    ) -> AsyncIterator[Measurement]:
        """Stream every measurement matching the listing filters, unpaginated.

        Shares the base query, ``_listing_conditions`` and
        ``MEASUREMENT_SORT_CLAUSES`` with ``get_measurement_listing``, so an
        export always carries the same rows in the same order as the listing.

        The caller's transaction must stay open for the whole iteration.
        """
        return stream_all(
            self.db,
            self._listing_base_query(),
            MEASUREMENT_SORT_CLAUSES[params.sort_order],
            conditions=self._listing_conditions(params),
        )

    async def count_for_export(self, params: MeasurementListingParams) -> int:
        """Return how many measurements the listing filters match, fetching none."""
        return await execute_count(
            self.db,
            self._listing_count_query(),
            conditions=self._listing_conditions(params),
        )

    async def get_latest_for_subject(self, subject_id: UUID) -> Measurement | None:
        """Return a subject's most recent measurement across every establishment.

        Returns None when the subject has never been measured; callers must not
        collapse that into a "normal" reading. ``id`` breaks ties between
        measurements sharing ``measured_at`` so the pick is deterministic.
        """
        result = await self.db.execute(
            select(Measurement)
            .where(Measurement.subject_id == subject_id)
            .options(selectinload(Measurement.establishment))
            .order_by(desc(Measurement.measured_at), desc(Measurement.id))
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_latest_for_subjects(
        self, subject_ids: list[UUID]
    ) -> dict[UUID, Measurement]:
        """Return each subject's most recent measurement, keyed by subject id.

        Subjects with no measurements are absent from the returned dict.
        """
        if not subject_ids:
            return {}
        result = await self.db.execute(
            select(Measurement)
            .where(Measurement.subject_id.in_(subject_ids))
            .options(selectinload(Measurement.establishment))
            .order_by(
                Measurement.subject_id,
                desc(Measurement.measured_at),
                desc(Measurement.id),
            )
            .distinct(Measurement.subject_id)
        )
        return {m.subject_id: m for m in result.scalars().all()}

    async def get_subject_evolution(
        self,
        subject_id: UUID,
        order: EvolutionOrder = EvolutionOrder.OLDEST_FIRST,
    ) -> list[Measurement]:
        """Return a subject's measurements ordered chronologically.

        ``order`` selects oldest-first (ascending) or newest-first (descending).
        """
        date_column = Measurement.measured_at
        order_by = (
            asc(date_column)
            if order == EvolutionOrder.OLDEST_FIRST
            else desc(date_column)
        )
        result = await self.db.execute(
            select(Measurement)
            .where(Measurement.subject_id == subject_id)
            .order_by(
                order_by,
                asc(Measurement.id)
                if order == EvolutionOrder.OLDEST_FIRST
                else desc(Measurement.id),
            )
        )
        return result.scalars().all()

    async def create(
        self,
        *,
        id: UUID | None,
        subject_id: UUID,
        responsible_id: UUID,
        establishment_id: UUID,
        weight_kg: float,
        height_cm: float,
        bmi: float,
        measured_at: datetime,
        observation: str | None = None,
        stature_method: str | None = None,
    ) -> Measurement:
        """Persist a new measurement. ``id`` is optional; when None the server
        generates it.

        The insert runs inside a SAVEPOINT so a unique violation rolls back only
        the failed row and leaves the session usable for the caller to re-query.

        Raises:
            UniqueConstraintError: If the id is already in use. The caller is
                responsible for re-querying to decide the outcome.
        """
        fields = dict(
            subject_id=subject_id,
            responsible_id=responsible_id,
            establishment_id=establishment_id,
            weight_kg=weight_kg,
            height_cm=height_cm,
            bmi=bmi,
            measured_at=measured_at,
            observation=observation,
            stature_method=stature_method,
        )
        if id is not None:
            fields["id"] = id
        measurement = Measurement(**fields)
        try:
            async with self.db.begin_nested():
                self.db.add(measurement)
                await self.db.flush()
        except IntegrityError:
            raise UniqueConstraintError("id", id)
        await self.db.refresh(measurement)
        return measurement
