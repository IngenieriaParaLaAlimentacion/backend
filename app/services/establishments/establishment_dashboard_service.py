from collections import defaultdict
from collections.abc import AsyncIterator
from uuid import UUID

from app.core.interfaces.unit_of_work import IUnitOfWork
from app.domain.establishment import EstablishmentDomain
from app.domain.establishment_dashboard import (
    EstablishmentAlertStatusDomain,
    EstablishmentDashboardDomain,
    EstablishmentFieldWorkerItemDomain,
    EstablishmentFieldWorkerListingParams,
    EstablishmentMapItemDomain,
    EstablishmentMetricsDomain,
    EstablishmentSubjectItemDomain,
    EstablishmentSubjectListingParams,
    StatusDistributionEntryDomain,
)
from app.domain.measurement import (
    ALERT_TO_STATUS,
    SEVERITY_RANK,
    STATUS_TO_SEVERITY,
    MeasurementSummaryDomain,
    NutritionalStatus,
    status_from_alerts,
)
from app.domain.pagination import PaginatedResult
from app.domain.user import UserActor
from app.reference_data.anthropometry import age_in_months
from app.services.access import check_establishment_access
from app.services.exporters.csv.csv_exporter import CsvExporter


def _round(value: float | None, digits: int = 2) -> float | None:
    """Round a possibly-absent average, keeping None as None."""
    return None if value is None else round(float(value), digits)


class EstablishmentDashboardService:
    """Business logic for the per-establishment analytics dashboard."""

    def __init__(self, uow: IUnitOfWork):
        self.uow = uow

    @staticmethod
    def _build_alert_status(rows: list, total: int) -> EstablishmentAlertStatusDomain:
        """Roll up per-subject nutritional states into an establishment-wide one.

        ``severity`` is the worst severity present among the subjects. No
        prevalence threshold is applied on purpose: the full distribution and
        ``at_risk_percentage`` travel in the response so the client decides how
        to word the banner.
        """
        counts: dict[NutritionalStatus, int] = {}
        for row in rows:
            status = (
                NutritionalStatus.NORMAL
                if row.alert_type is None
                else ALERT_TO_STATUS[row.alert_type]
            )
            counts[status] = counts.get(status, 0) + row.count

        distribution = [
            StatusDistributionEntryDomain(
                status=status,
                severity=STATUS_TO_SEVERITY[status],
                count=count,
                percentage=round(count * 100 / total, 2),
            )
            for status, count in counts.items()
        ]
        # Largest group first; ties break towards the more severe status so the
        # dominant one is never the reassuring half of a 50/50 split.
        distribution.sort(
            key=lambda entry: (entry.count, SEVERITY_RANK[entry.severity]),
            reverse=True,
        )

        at_risk_count = total - counts.get(NutritionalStatus.NORMAL, 0)
        severity = max(
            (entry.severity for entry in distribution),
            key=lambda s: SEVERITY_RANK[s],
            default=None,
        )

        return EstablishmentAlertStatusDomain(
            severity=severity,
            dominant_status=distribution[0].status if distribution else None,
            total_evaluated=total,
            at_risk_count=at_risk_count,
            at_risk_percentage=round(at_risk_count * 100 / total, 2),
            distribution=distribution,
        )

    @classmethod
    def _build_map_item(
        cls, establishment: EstablishmentDomain, rows: list
    ) -> EstablishmentMapItemDomain:
        """Build one establishment's map item from its status-distribution rows."""
        total = sum(row.count for row in rows)
        # Same builder as the individual dashboard, so severity and
        # dominant_status cannot drift from what the establishment ficha shows.
        alert_status = (
            cls._build_alert_status(rows, total)
            if total > 0
            else EstablishmentAlertStatusDomain.empty()
        )
        return EstablishmentMapItemDomain(
            id=establishment.id,
            name=establishment.name,
            latitude=establishment.latitude,
            longitude=establishment.longitude,
            has_data=total > 0,
            severity=alert_status.severity,
            dominant_status=alert_status.dominant_status,
        )

    @staticmethod
    def _build_subject_item(
        measurement, measurement_count: int
    ) -> EstablishmentSubjectItemDomain:
        """Build a listing item from a subject's latest measurement."""
        subject = measurement.subject
        return EstablishmentSubjectItemDomain(
            id=subject.id,
            dni=subject.dni,
            name=subject.name,
            last_name=subject.last_name,
            sex=subject.sex,
            birth_date=subject.birth_date,
            age_months=age_in_months(subject.birth_date, measurement.measured_at),
            measurement_count=measurement_count,
            nutritional_status=status_from_alerts(measurement.alerts),
            latest_measurement=MeasurementSummaryDomain.from_db(measurement),
        )

    async def get_establishment_dashboard(
        self, establishment_id: UUID, actor: UserActor
    ) -> EstablishmentDashboardDomain:
        """Return identification data, aggregated metrics and the alert state
        for one establishment.

        Raises:
            EstablishmentNotFoundError: If the establishment does not exist.
            EstablishmentAccessDeniedError: field worker lacks approved access.
        """
        establishment = await self.uow.establishment_repo.get_by_id_or_raise(
            establishment_id
        )
        await check_establishment_access(self.uow, actor, establishment_id)

        movements = await self.uow.establishment_dashboard_repo.get_last_movement_dates(
            establishment_id
        )
        row = await self.uow.establishment_dashboard_repo.get_metrics(establishment_id)
        subject_count = row.subject_count or 0

        if subject_count == 0:
            empty = EstablishmentMetricsDomain.empty()
            empty.last_intake_at = movements.last_intake_at
            empty.last_outflow_at = movements.last_outflow_at
            return EstablishmentDashboardDomain(
                establishment=EstablishmentDomain.from_db(establishment),
                has_data=False,
                metrics=empty,
                alert_status=EstablishmentAlertStatusDomain.empty(),
            )

        measurement_count = (
            await self.uow.establishment_dashboard_repo.count_measurements(
                establishment_id
            )
        )
        metrics = EstablishmentMetricsDomain(
            subject_count=subject_count,
            measurement_count=measurement_count,
            last_measured_at=row.last_measured_at,
            avg_height_cm=_round(row.avg_height_cm),
            avg_weight_kg=_round(row.avg_weight_kg),
            avg_bmi=_round(row.avg_bmi),
            # Completed months, not a 2-decimal average: _round would give a float.
            avg_age_months=round(float(row.avg_age_months)),
            last_intake_at=movements.last_intake_at,
            last_outflow_at=movements.last_outflow_at,
        )

        rows = await self.uow.establishment_dashboard_repo.get_status_distribution(
            establishment_id
        )
        alert_status = self._build_alert_status(rows, subject_count)

        return EstablishmentDashboardDomain(
            establishment=EstablishmentDomain.from_db(establishment),
            has_data=True,
            metrics=metrics,
            alert_status=alert_status,
        )

    async def get_establishments_map(self) -> list[EstablishmentMapItemDomain]:
        """Return every establishment's location and rolled-up nutritional
        severity, for plotting on a map.

        An establishment with no measurements gets has_data=False and no
        severity.
        """
        establishments = [
            EstablishmentDomain.from_db(establishment)
            for establishment in await self.uow.establishment_repo.get_all()
        ]
        rows = await (
            self.uow.establishment_dashboard_repo.get_status_distribution_for_all()
        )

        rows_by_establishment: dict[UUID, list] = defaultdict(list)
        for row in rows:
            rows_by_establishment[row.establishment_id].append(row)

        return [
            self._build_map_item(
                establishment, rows_by_establishment.get(establishment.id, [])
            )
            for establishment in establishments
        ]

    async def list_establishment_subjects(
        self,
        establishment_id: UUID,
        page: int,
        page_size: int,
        params: EstablishmentSubjectListingParams,
    ) -> PaginatedResult[EstablishmentSubjectItemDomain]:
        """Return the subjects attending an establishment, enriched with their
        latest measurement and nutritional status.

        Raises:
            EstablishmentNotFoundError: If the establishment does not exist.
        """
        await self.uow.establishment_repo.get_by_id_or_raise(establishment_id)

        page = max(1, page)
        offset = (page - 1) * page_size
        rows, total = await self.uow.establishment_dashboard_repo.get_subject_listing(
            establishment_id=establishment_id,
            limit=page_size,
            offset=offset,
            params=params,
        )

        items = [
            self._build_subject_item(row.Measurement, row.measurement_count)
            for row in rows
        ]
        return PaginatedResult.build(
            items=items, total=total, page=page, page_size=page_size
        )

    def export_establishment_subjects(
        self,
        establishment_id: UUID,
        params: EstablishmentSubjectListingParams,
        exporter: CsvExporter[EstablishmentSubjectItemDomain],
    ) -> AsyncIterator[bytes]:
        """Stream the establishment's subject listing as an exported file's bytes.

        Applies the same filters and order as ``list_establishment_subjects``
        over the whole result set rather than one page.
        """
        rows = (
            self._build_subject_item(row.Measurement, row.measurement_count)
            async for row in self.uow.establishment_dashboard_repo.stream_for_export(
                establishment_id=establishment_id, params=params
            )
        )
        return exporter.stream(rows)

    async def prepare_establishment_export(
        self,
        establishment_id: UUID,
        params: EstablishmentSubjectListingParams,
    ) -> tuple[str, int]:
        """Resolve the establishment and size the export before streaming.

        Returns its name (for the download filename) and the row count (for the
        row-count header). Runs as a pre-flight so an unknown establishment
        answers a real 404 instead of a truncated file.

        Raises:
            EstablishmentNotFoundError: If the establishment does not exist.
        """
        establishment = await self.uow.establishment_repo.get_by_id_or_raise(
            establishment_id
        )
        total = await self.uow.establishment_dashboard_repo.count_for_export(
            establishment_id=establishment_id, params=params
        )
        return establishment.name, total

    async def list_establishment_field_workers(
        self,
        establishment_id: UUID,
        page: int,
        page_size: int,
        params: EstablishmentFieldWorkerListingParams,
    ) -> PaginatedResult[EstablishmentFieldWorkerItemDomain]:
        """Return the users enrolled in an establishment and their activity there.

        Raises:
            EstablishmentNotFoundError: If the establishment does not exist.
        """
        await self.uow.establishment_repo.get_by_id_or_raise(establishment_id)

        page = max(1, page)
        offset = (page - 1) * page_size
        (
            rows,
            total,
        ) = await self.uow.establishment_dashboard_repo.get_field_worker_listing(
            establishment_id=establishment_id,
            limit=page_size,
            offset=offset,
            params=params,
        )

        items = [
            EstablishmentFieldWorkerItemDomain(
                id=row.User.id,
                name=row.User.name,
                last_name=row.User.last_name,
                email=row.User.email,
                user_status=row.User.status,
                relation_status=row.relation_status,
                measurement_count=row.measurement_count,
                last_measured_at=row.last_measured_at,
            )
            for row in rows
        ]
        return PaginatedResult.build(
            items=items, total=total, page=page, page_size=page_size
        )
