from uuid import UUID

from sqlalchemy import Row, asc, desc, extract, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import contains_eager

from app.domain.establishment_dashboard import (
    EstablishmentFieldWorkerListingParams,
    EstablishmentSubjectListingParams,
    EstablishmentSubjectSortOrder,
)
from app.models.establishment import Establishment
from app.models.measurement import Measurement
from app.models.measurement_alert import MeasurementAlert
from app.models.subject import Subject
from app.models.user import User
from app.models.user_establishment import UserEstablishment
from app.repositories.subject_repository import subject_search_condition
from app.utils.db import escape_like

# Completed months between a subject's birth date and the moment they were
# measured. Postgres ``age()`` returns an interval of full years/months/days,
# which is exactly the semantics of ``app.utils.anthropometry.age_in_months``.
_AGE_MONTHS = extract(
    "year", func.age(Measurement.measured_at, Subject.birth_date)
) * 12 + extract("month", func.age(Measurement.measured_at, Subject.birth_date))

# Maps each EstablishmentSubjectSortOrder value to its SQLAlchemy order clause.
# KeyError on an unmapped value is intentional: it surfaces missing cases immediately.
# Older birth_date means older subject, hence the inversion on the AGE_* orders.
_SUBJECT_SORT_CLAUSES = {
    EstablishmentSubjectSortOrder.MEASURED_AT_DESC: desc(Measurement.measured_at),
    EstablishmentSubjectSortOrder.MEASURED_AT_ASC: asc(Measurement.measured_at),
    EstablishmentSubjectSortOrder.NAME_ASC: asc(Subject.last_name),
    EstablishmentSubjectSortOrder.NAME_DESC: desc(Subject.last_name),
    EstablishmentSubjectSortOrder.BMI_DESC: desc(Measurement.bmi),
    EstablishmentSubjectSortOrder.BMI_ASC: asc(Measurement.bmi),
    EstablishmentSubjectSortOrder.AGE_DESC: asc(Subject.birth_date),
    EstablishmentSubjectSortOrder.AGE_ASC: desc(Subject.birth_date),
}


class EstablishmentDashboardRepository:
    """Aggregation queries backing the per-establishment dashboard."""

    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def _latest_per_subject(establishment_id: UUID):
        """Subquery: id of each subject's most recent measurement here.

        Uses Postgres DISTINCT ON, whose distinct expression must lead the
        ORDER BY; ``id`` breaks ties between measurements sharing ``measured_at``
        so the pick is deterministic. Selecting only the id (rather than the
        whole entity) lets callers join it and then order the outer query
        freely, which DISTINCT ON would otherwise forbid.
        """
        return (
            select(Measurement.id.label("id"))
            .where(Measurement.establishment_id == establishment_id)
            .distinct(Measurement.subject_id)
            .order_by(
                Measurement.subject_id,
                desc(Measurement.measured_at),
                desc(Measurement.id),
            )
            .subquery()
        )

    async def get_metrics(self, establishment_id: UUID) -> Row:
        """Return one row of aggregated metrics over each subject's latest
        measurement at this establishment.

        Averages are None when the establishment has no measurements, which the
        service surfaces as an explicit empty state rather than zeros.
        """
        latest = self._latest_per_subject(establishment_id)
        result = await self.db.execute(
            select(
                func.count().label("subject_count"),
                func.max(Measurement.measured_at).label("last_measured_at"),
                func.avg(Measurement.height_cm).label("avg_height_cm"),
                func.avg(Measurement.weight_kg).label("avg_weight_kg"),
                func.avg(Measurement.bmi).label("avg_bmi"),
                func.avg(_AGE_MONTHS).label("avg_age_months"),
            )
            .select_from(latest)
            .join(Measurement, Measurement.id == latest.c.id)
            .join(Subject, Measurement.subject_id == Subject.id)
        )
        return result.one()

    async def count_measurements(self, establishment_id: UUID) -> int:
        """Return the total number of measurements ever taken here."""
        result = await self.db.execute(
            select(func.count())
            .select_from(Measurement)
            .where(Measurement.establishment_id == establishment_id)
        )
        return result.scalar_one()

    async def get_status_distribution(self, establishment_id: UUID) -> list[Row]:
        """Return (alert_type, severity, count) over each subject's latest
        measurement at this establishment.

        The join to alerts is an OUTER join on purpose: subjects whose latest
        measurement raised no alert are the healthy ones, and a plain join would
        drop them from the distribution entirely. They come back with a NULL
        alert_type, which the service maps to NutritionalStatus.NORMAL.
        """
        latest = self._latest_per_subject(establishment_id)
        result = await self.db.execute(
            select(
                MeasurementAlert.alert_type,
                MeasurementAlert.severity,
                func.count().label("count"),
            )
            .select_from(latest)
            .outerjoin(MeasurementAlert, MeasurementAlert.measurement_id == latest.c.id)
            .group_by(MeasurementAlert.alert_type, MeasurementAlert.severity)
        )
        return list(result.all())

    async def get_subject_listing(
        self,
        establishment_id: UUID,
        limit: int,
        offset: int,
        params: EstablishmentSubjectListingParams,
    ) -> tuple[list[Row], int]:
        """Return a paginated list of the subjects attending this establishment.

        One row per subject, carrying their most recent measurement here plus
        how many measurements they have at this establishment. ``search``
        behaves exactly as in the general subject listing.
        """
        latest = self._latest_per_subject(establishment_id)
        measurement_count = (
            select(func.count(Measurement.id))
            .where(
                Measurement.establishment_id == establishment_id,
                Measurement.subject_id == Subject.id,
            )
            .correlate(Subject)
            .scalar_subquery()
        )

        base_query = (
            select(Measurement, measurement_count.label("measurement_count"))
            .select_from(latest)
            .join(Measurement, Measurement.id == latest.c.id)
            .join(Subject, Measurement.subject_id == Subject.id)
            .join(Establishment, Measurement.establishment_id == Establishment.id)
            .options(
                contains_eager(Measurement.subject),
                contains_eager(Measurement.establishment),
            )
        )
        count_query = (
            select(func.count())
            .select_from(latest)
            .join(Measurement, Measurement.id == latest.c.id)
            .join(Subject, Measurement.subject_id == Subject.id)
        )

        condition = subject_search_condition(params.search)
        if condition is not None:
            base_query = base_query.where(condition)
            count_query = count_query.where(condition)

        order_by = _SUBJECT_SORT_CLAUSES[params.sort_order]
        total = (await self.db.execute(count_query)).scalar_one()
        rows = await self.db.execute(
            base_query.order_by(order_by, asc(Subject.id)).limit(limit).offset(offset)
        )
        return list(rows.all()), total

    @staticmethod
    def _field_worker_search_condition(search: str | None):
        """Case-insensitive name/last-name/email match for ``search``, or None."""
        if not search:
            return None
        search_term = f"%{escape_like(search)}%"
        return (
            User.name.ilike(search_term, escape="\\")
            | User.last_name.ilike(search_term, escape="\\")
            | User.email.ilike(search_term, escape="\\")
        )

    async def get_field_worker_listing(
        self,
        establishment_id: UUID,
        limit: int,
        offset: int,
        params: EstablishmentFieldWorkerListingParams,
    ) -> tuple[list[Row], int]:
        """Return a paginated list of the users enrolled in this establishment,
        with how many measurements each has taken here and when they last did.
        """
        taken_count = (
            select(func.count(Measurement.id))
            .where(
                Measurement.establishment_id == establishment_id,
                Measurement.responsible_id == User.id,
            )
            .correlate(User)
            .scalar_subquery()
        )
        last_measured_at = (
            select(func.max(Measurement.measured_at))
            .where(
                Measurement.establishment_id == establishment_id,
                Measurement.responsible_id == User.id,
            )
            .correlate(User)
            .scalar_subquery()
        )

        base_query = (
            select(
                User,
                UserEstablishment.status.label("relation_status"),
                taken_count.label("measurement_count"),
                last_measured_at.label("last_measured_at"),
            )
            .join(UserEstablishment, UserEstablishment.user_id == User.id)
            .where(
                UserEstablishment.establishment_id == establishment_id,
                UserEstablishment.status == params.relation_status,
            )
        )
        count_query = (
            select(func.count())
            .select_from(User)
            .join(UserEstablishment, UserEstablishment.user_id == User.id)
            .where(
                UserEstablishment.establishment_id == establishment_id,
                UserEstablishment.status == params.relation_status,
            )
        )

        condition = self._field_worker_search_condition(params.search)
        if condition is not None:
            base_query = base_query.where(condition)
            count_query = count_query.where(condition)

        total = (await self.db.execute(count_query)).scalar_one()
        rows = await self.db.execute(
            base_query.order_by(asc(User.last_name), asc(User.id))
            .limit(limit)
            .offset(offset)
        )
        return list(rows.all()), total
