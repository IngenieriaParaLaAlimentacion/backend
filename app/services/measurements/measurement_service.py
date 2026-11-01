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
    SubjectNotFoundError,
    UniqueConstraintError,
)
from app.models.subjects.subject import Subject
from app.reference_data.anthropometry import evaluate_alerts
from app.schemas.measurements.measurement_schema import MeasurementRequest
from app.services.access import check_establishment_access
from app.services.exporters.csv.csv_exporter import CsvExporter


class MeasurementService:
    """Business logic for anthropometric measurement registration."""

    def __init__(self, uow: IUnitOfWork) -> None:
        self.uow = uow

    async def _get_subject_or_raise(self, subject_id: UUID) -> Subject:
        subject = await self.uow.subject_repo.get_by_id(subject_id)
        if subject is None:
            raise SubjectNotFoundError(str(subject_id))
        return subject

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
            existing = await self.uow.measurement_repo.get_by_id(data.id)
            if existing is not None:
                return MeasurementDomain.from_db(existing), False

        subject = await self._get_subject_or_raise(data.subject_id)
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
            )
        except UniqueConstraintError:
            # Concurrent insert of the same id (race) -> treat as replay.
            if data.id is not None:
                raced = await self.uow.measurement_repo.get_by_id(data.id)
                if raced is not None:
                    return MeasurementDomain.from_db(raced), False
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

        await self.uow.commit()
        return MeasurementDomain.from_db(measurement), True

    async def list_measurements(
        self,
        page: int,
        page_size: int,
        params: MeasurementListingParams,
    ) -> PaginatedResult[MeasurementListItemDomain]:
        """Return a paginated, filtered and sorted list of measurements."""
        page = max(1, page)
        offset = (page - 1) * page_size
        measurements, total = await self.uow.measurement_repo.get_measurement_listing(
            limit=page_size, offset=offset, params=params
        )
        return PaginatedResult.build(
            items=[MeasurementListItemDomain.from_db(m) for m in measurements],
            total=total,
            page=page,
            page_size=page_size,
        )

    def export_measurement_listing(
        self,
        params: MeasurementListingParams,
        exporter: CsvExporter[MeasurementListItemDomain],
    ) -> AsyncIterator[bytes]:
        """Stream the measurement listing as an exported file's bytes.

        Applies the same filters and order as ``list_measurements`` over the
        whole result set rather than one page. The caller's UnitOfWork must
        outlive the returned iterator.
        """
        rows = (
            MeasurementListItemDomain.from_db(m)
            async for m in self.uow.measurement_repo.stream_for_export(params)
        )
        return exporter.stream(rows)

    async def count_measurement_export(self, params: MeasurementListingParams) -> int:
        """How many rows the export will contain, for the row-count header."""
        return await self.uow.measurement_repo.count_for_export(params)

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
        subject = await self._get_subject_or_raise(subject_id)
        measurements = await self.uow.measurement_repo.get_subject_evolution(
            subject_id, order=order
        )
        return SubjectEvolutionDomain(
            subject=SubjectRefDomain.from_db(subject),
            points=[EvolutionPointDomain.from_db(m) for m in measurements],
        )
