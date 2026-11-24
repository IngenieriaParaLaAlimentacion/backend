from collections.abc import AsyncIterator
from uuid import UUID

from app.core.interfaces.unit_of_work import IUnitOfWork
from app.domain.measurement import (
    EvolutionOrder,
    MeasurementDomain,
    MeasurementListingParams,
    MeasurementListItemDomain,
    SubjectRefDomain,
)
from app.domain.pagination import PaginatedResult
from app.domain.subject_detail import EvolutionPointDomain, SubjectEvolutionDomain
from app.domain.user import UserActor
from app.exceptions.domain_exceptions import (
    EmptyUpdateRequestError,
    MeasurementNotFoundError,
    SubjectNotFoundError,
    UniqueConstraintError,
)
from app.models.subjects.subject import Subject
from app.reference_data.anthropometry import evaluate_alerts
from app.reference_data.sap_reference import configured_ruleset, visible_ruleset
from app.schemas.measurements.measurement_schema import (
    MeasurementCorrectionRequest,
    MeasurementRequest,
)
from app.services.access import check_establishment_access
from app.services.exporters.csv.csv_exporter import CsvExporter
from app.services.measurements.assessment_projection import (
    assessments_by_id,
    begin_assessment_read,
    resolve_assessment_filters,
)
from app.services.measurements.assessment_service import persist_assessments
from app.utils.db import achunked

_ASSESSMENT_BATCH_SIZE = 500


class MeasurementService:
    """Business logic for anthropometric measurement registration."""

    def __init__(self, uow: IUnitOfWork) -> None:
        self.uow = uow

    async def _get_subject_or_raise(self, subject_id: UUID) -> Subject:
        subject = await self.uow.subject_repo.get_by_id(subject_id)
        if subject is None:
            raise SubjectNotFoundError(str(subject_id))
        return subject

    async def _lock_subject_or_raise(self, subject_id: UUID) -> Subject:
        subject = await self.uow.subject_repo.get_for_update(subject_id)
        if subject is None:
            raise SubjectNotFoundError(str(subject_id))
        return subject

    async def _find_replay(self, measurement_id: UUID) -> MeasurementDomain | None:
        ruleset = visible_ruleset()
        if ruleset is None:
            measurement = await self.uow.measurement_repo.get_by_id(measurement_id)
            return MeasurementDomain.from_db(measurement) if measurement else None
        stored = await self.uow.measurement_repo.get_by_id_with_assessments(
            measurement_id, ruleset.version
        )
        return MeasurementDomain.from_db(*stored) if stored is not None else None

    async def register(
        self,
        data: MeasurementRequest,
        actor: UserActor,
    ) -> tuple[MeasurementDomain, bool]:
        """Idempotently register a measurement.

        Returns a ``(measurement, created)`` tuple: ``created`` is True for a brand-new
        measurement (201) and False for an idempotent replay of an existing id (200).

        Raises:
            SubjectNotFoundError: subject_id does not exist.
            EstablishmentNotFoundError: establishment_id does not exist.
            EstablishmentAccessDeniedError: field worker lacks approved access to
                the establishment.
        """
        if data.id is not None:
            existing = await self._find_replay(data.id)
            if existing is not None:
                return existing, False

        subject = await self._lock_subject_or_raise(data.subject_id)
        await self.uow.establishment_repo.get_by_id_or_raise(data.establishment_id)
        await check_establishment_access(self.uow, actor, data.establishment_id)

        bmi = data.weight_kg / (data.height_cm / 100) ** 2

        try:
            measurement = await self.uow.measurement_repo.create(
                id=data.id,
                subject_id=data.subject_id,
                responsible_id=actor.user_id,
                establishment_id=data.establishment_id,
                weight_kg=data.weight_kg,
                height_cm=data.height_cm,
                bmi=bmi,
                measured_at=data.measured_at,
                observation=data.observation,
                stature_method=data.stature_method,
            )
        except UniqueConstraintError:
            # Concurrent insert of the same id (race) -> treat as replay.
            if data.id is not None:
                raced = await self._find_replay(data.id)
                if raced is not None:
                    return raced, False
            raise

        raw_alerts = evaluate_alerts(
            bmi=bmi,
            sex=subject.sex,
            birth_date=subject.birth_date,
            measured_at=data.measured_at,
        )
        if raw_alerts:
            measurement.alerts = await self.uow.measurement_alert_repo.create_bulk(
                measurement.id, raw_alerts
            )

        result = await self._persist_and_project(measurement, subject)
        await self.uow.commit()
        return result, True

    async def correct(
        self, measurement_id: UUID, data: MeasurementCorrectionRequest, actor: UserActor
    ) -> MeasurementDomain:
        """Correct clinical values and replace their assessments atomically."""
        fields = data.model_dump(exclude_unset=True)
        if not fields:
            raise EmptyUpdateRequestError()

        measurement = await self.uow.measurement_repo.get_by_id(measurement_id)
        if measurement is None:
            raise MeasurementNotFoundError(str(measurement_id))
        await check_establishment_access(self.uow, actor, measurement.establishment_id)
        subject = await self._lock_subject_or_raise(measurement.subject_id)
        measurement = await self.uow.measurement_repo.get_current_by_id(measurement_id)
        if measurement is None:
            raise MeasurementNotFoundError(str(measurement_id))

        fields["bmi"] = (
            fields.get("weight_kg", measurement.weight_kg)
            / (fields.get("height_cm", measurement.height_cm) / 100) ** 2
        )
        measurement = await self.uow.measurement_repo.update(measurement, fields)
        await refresh_legacy_alerts(self.uow, measurement, subject)
        result = await self._persist_and_project(measurement, subject, corrected=True)
        await self.uow.commit()
        return result

    async def _persist_and_project(
        self, measurement, subject, *, corrected: bool = False
    ) -> MeasurementDomain:
        ruleset = configured_ruleset()
        if corrected:
            await self.uow.measurement_assessment_repo.invalidate_other_versions(
                [measurement.id], ruleset.version if ruleset is not None else None
            )
        assessments = (
            await persist_assessments(self.uow, measurement, subject, ruleset)
            if ruleset is not None
            else None
        )
        return MeasurementDomain.from_db(
            measurement, assessments if visible_ruleset() is not None else None
        )

    async def list_measurements(
        self,
        page: int,
        page_size: int,
        params: MeasurementListingParams,
    ) -> PaginatedResult[MeasurementListItemDomain]:
        """Return a paginated, filtered and sorted list of measurements."""
        await begin_assessment_read(self.uow)
        page = max(1, page)
        offset = (page - 1) * page_size
        measurements, total = await self.uow.measurement_repo.get_measurement_listing(
            limit=page_size, offset=offset, params=resolve_assessment_filters(params)
        )
        assessments = await assessments_by_id(self.uow, (m.id for m in measurements))
        return PaginatedResult.build(
            items=[
                MeasurementListItemDomain.from_db(m, assessments.get(m.id))
                for m in measurements
            ],
            total=total,
            page=page,
            page_size=page_size,
        )

    def export_measurement_listing(
        self,
        params: MeasurementListingParams,
        exporter: CsvExporter[MeasurementListItemDomain],
        *,
        assessment_fields: bool = False,
    ) -> AsyncIterator[bytes]:
        """Stream the measurement listing as an exported file's bytes.

        Applies the same filters and order as ``list_measurements`` over the
        whole result set rather than one page. The caller's UnitOfWork must
        outlive the returned iterator.
        """
        source = self.uow.measurement_repo.stream_for_export(
            resolve_assessment_filters(params)
        )
        return exporter.stream(self._stream_listing_items(source, assessment_fields))

    async def _stream_listing_items(
        self, source: AsyncIterator, assessment_fields: bool
    ) -> AsyncIterator[MeasurementListItemDomain]:
        await begin_assessment_read(self.uow)
        if not assessment_fields:
            async for measurement in source:
                yield MeasurementListItemDomain.from_db(measurement)
            return
        async for batch in achunked(source, _ASSESSMENT_BATCH_SIZE):
            assessments = await assessments_by_id(self.uow, (m.id for m in batch))
            for measurement in batch:
                yield MeasurementListItemDomain.from_db(
                    measurement, assessments.get(measurement.id)
                )

    async def count_measurement_export(self, params: MeasurementListingParams) -> int:
        """How many rows the export will contain, for the row-count header."""
        return await self.uow.measurement_repo.count_for_export(
            resolve_assessment_filters(params)
        )

    async def get_subject_evolution(
        self,
        subject_id: UUID,
        order: EvolutionOrder = EvolutionOrder.OLDEST_FIRST,
    ) -> SubjectEvolutionDomain:
        """Return a subject's chronological anthropometric evolution.

        ``order`` selects oldest-first (default) or newest-first.

        Raises:
            SubjectNotFoundError: if no subject with the given id exists.
        """
        await begin_assessment_read(self.uow)
        subject = await self._get_subject_or_raise(subject_id)
        measurements = await self.uow.measurement_repo.get_subject_evolution(
            subject_id, order=order
        )
        assessments = await assessments_by_id(self.uow, (m.id for m in measurements))
        return SubjectEvolutionDomain(
            subject=SubjectRefDomain.from_db(subject),
            points=[
                EvolutionPointDomain.from_db(m, assessments.get(m.id))
                for m in measurements
            ],
        )


async def refresh_legacy_alerts(
    uow: IUnitOfWork, measurement, subject: Subject
) -> None:
    """Update the legacy projection for corrected measurements."""
    alerts = evaluate_alerts(
        bmi=measurement.bmi,
        sex=subject.sex,
        birth_date=subject.birth_date,
        measured_at=measurement.measured_at,
    )
    await uow.measurement_alert_repo.replace_for_measurement(measurement, alerts)
