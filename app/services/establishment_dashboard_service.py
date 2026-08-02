from uuid import UUID

from app.core.interfaces.unit_of_work import IUnitOfWork
from app.domain.establishment import EstablishmentDomain
from app.domain.establishment_dashboard import (
    EstablishmentAlertStatusDomain,
    EstablishmentDashboardDomain,
    EstablishmentFieldWorkerItemDomain,
    EstablishmentFieldWorkerListingParams,
    EstablishmentMetricsDomain,
    EstablishmentSubjectItemDomain,
    EstablishmentSubjectListingParams,
    LatestMeasurementAtEstablishmentDomain,
    StatusDistributionEntryDomain,
)
from app.domain.measurement import (
    ALERT_TO_STATUS,
    SEVERITY_RANK,
    STATUS_TO_SEVERITY,
    NutritionalStatus,
    status_from_alerts,
)
from app.domain.pagination import PaginatedResult
from app.exceptions.domain_exceptions import EstablishmentNotFoundError
from app.models.establishment import Establishment
from app.utils.anthropometry import age_in_months


def _round(value: float | None, digits: int = 2) -> float | None:
    """Round a possibly-absent average, keeping None as None."""
    return None if value is None else round(float(value), digits)


class EstablishmentDashboardService:
    """Business logic for the per-establishment analytics dashboard."""

    def __init__(self, uow: IUnitOfWork):
        self.uow = uow

    async def _get_establishment(self, establishment_id: UUID) -> Establishment:
        """Return the establishment or raise if it does not exist.

        Every dashboard endpoint resolves the establishment first so an unknown
        id answers 404 rather than an empty page, which would be
        indistinguishable from a real establishment with no data.
        """
        establishment = await self.uow.establishment_repo.get_by_id(establishment_id)
        if establishment is None:
            raise EstablishmentNotFoundError(str(establishment_id))
        return establishment

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
            latest_measurement=LatestMeasurementAtEstablishmentDomain.from_db(measurement),
        )

    async def get_establishment_dashboard(
        self, establishment_id: UUID
    ) -> EstablishmentDashboardDomain:
        """Return identification data, aggregated metrics and the alert state
        for one establishment.

        Raises:
            EstablishmentNotFoundError: If the establishment does not exist.
        """
        establishment = await self._get_establishment(establishment_id)

        row = await self.uow.establishment_dashboard_repo.get_metrics(establishment_id)
        subject_count = row.subject_count or 0

        if subject_count == 0:
            return EstablishmentDashboardDomain(
                establishment=EstablishmentDomain.from_db(establishment),
                has_data=False,
                metrics=EstablishmentMetricsDomain.empty(),
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
            avg_age_months=round(float(row.avg_age_months)),
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
        await self._get_establishment(establishment_id)

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
        await self._get_establishment(establishment_id)

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
