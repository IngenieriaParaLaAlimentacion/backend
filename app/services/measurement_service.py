from uuid import UUID

from app.core.interfaces.unit_of_work import IUnitOfWork
from app.domain.establishment import UserEstablishmentStatus
from app.domain.measurement import AlertDomain, MeasurementDomain
from app.domain.user import UserActor, UserRole
from app.exceptions.domain_exceptions import (
    EstablishmentNotFoundError,
    ForbiddenError,
    SubjectNotFoundError,
)
from app.models.subject import Subject
from app.schemas.measurement_schema import MeasurementRequest
from app.utils.anthropometry import evaluate_alerts


class MeasurementService:
    """Business logic for anthropometric measurement registration."""

    def __init__(self, uow: IUnitOfWork) -> None:
        self.uow = uow

    async def _get_subject_or_raise(self, subject_id: UUID) -> Subject:
        subject = await self.uow.subject_repo.get_by_id(subject_id)
        if subject is None:
            raise SubjectNotFoundError(str(subject_id))
        return subject

    async def _get_establishment_or_raise(self, establishment_id: UUID) -> None:
        establishment = await self.uow.establishment_repo.get_by_id(establishment_id)
        if establishment is None:
            raise EstablishmentNotFoundError(str(establishment_id))

    async def _check_establishment_access(
        self, actor: UserActor, establishment_id: UUID
    ) -> None:
        if actor.role != UserRole.ESTABLISHMENT_MANAGER:
            return
        relation = await self.uow.user_establishment_repo.get_relation(
            actor.user_id, establishment_id
        )
        if relation is None or relation.status != UserEstablishmentStatus.APPROVED:
            raise ForbiddenError()

    async def _upsert_with_alerts(
        self,
        idempotency_key: UUID,
        data: MeasurementRequest,
        actor: UserActor,
        subject: Subject,
        bmi: float,
    ):
        measurement, is_new = await self.uow.measurement_repo.upsert_by_idempotency_key(
            idempotency_key=idempotency_key,
            subject_id=data.subject_id,
            responsible_id=actor.user_id,
            establishment_id=data.establishment_id,
            weight_kg=data.weight_kg,
            height_cm=data.height_cm,
            bmi=bmi,
            measured_at=data.measured_at,
        )
        if is_new:
            raw_alerts = evaluate_alerts(
                bmi=bmi,
                sex=subject.sex,
                birth_date=subject.birth_date,
                measured_at=data.measured_at,
            )
            if raw_alerts:
                await self.uow.measurement_alert_repo.create_bulk(
                    measurement.id, raw_alerts
                )
        return measurement

    async def _to_domain(self, measurement) -> MeasurementDomain:
        alert_rows = await self.uow.measurement_alert_repo.get_by_measurement_id(
            measurement.id
        )
        return MeasurementDomain(
            id=measurement.id,
            idempotency_key=measurement.idempotency_key,
            subject_id=measurement.subject_id,
            responsible_id=measurement.responsible_id,
            establishment_id=measurement.establishment_id,
            weight_kg=measurement.weight_kg,
            height_cm=measurement.height_cm,
            bmi=measurement.bmi,
            measured_at=measurement.measured_at,
            created_at=measurement.created_at,
            alerts=[AlertDomain.from_db(a) for a in alert_rows],
        )

    async def register(
        self,
        idempotency_key: UUID,
        data: MeasurementRequest,
        actor: UserActor,
    ) -> MeasurementDomain:
        """Register a measurement idempotently.

        Returns the stored record unchanged if idempotency_key was already seen.

        Raises:
            SubjectNotFoundError: subject_id does not exist.
            EstablishmentNotFoundError: establishment_id does not exist.
            ForbiddenError: manager lacks approved access to the establishment.
        """
        subject = await self._get_subject_or_raise(data.subject_id)
        await self._get_establishment_or_raise(data.establishment_id)
        await self._check_establishment_access(actor, data.establishment_id)

        bmi = data.weight_kg / (data.height_cm / 100) ** 2
        measurement = await self._upsert_with_alerts(
            idempotency_key, data, actor, subject, bmi
        )
        await self.uow.commit()
        return await self._to_domain(measurement)
