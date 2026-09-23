from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.notifications import PushDeliveryContext
from app.models.establishments.establishment import Establishment
from app.models.notifications.push_delivery_job import PushDeliveryJob
from app.models.notifications.stale_establishment_cycle import (
    StaleEstablishmentCycle,
)
from app.models.notifications.user_push_device import UserPushDevice


class PushDeliveryJobRepository:
    """Database operations for outstanding push-delivery work."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_for_devices(
        self,
        *,
        stale_cycle_id: UUID,
        threshold_hours: int,
        device_ids: list[UUID],
        available_at: datetime,
    ) -> list[PushDeliveryJob]:
        """Stage one delivery job for every current target device."""
        jobs = [
            PushDeliveryJob(
                stale_cycle_id=stale_cycle_id,
                device_id=device_id,
                threshold_hours=threshold_hours,
                available_at=available_at,
            )
            for device_id in device_ids
        ]
        self.db.add_all(jobs)
        return jobs

    async def claim_due(
        self, *, now: datetime, claimed_until: datetime, limit: int
    ) -> list[UUID]:
        """Lease available or expired jobs and return their IDs."""
        result = await self.db.execute(
            select(PushDeliveryJob)
            .where(
                PushDeliveryJob.available_at <= now,
                or_(
                    PushDeliveryJob.claimed_until.is_(None),
                    PushDeliveryJob.claimed_until <= now,
                ),
            )
            .order_by(PushDeliveryJob.available_at, PushDeliveryJob.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        jobs = list(result.scalars().all())
        for job in jobs:
            job.claimed_until = claimed_until
        return [job.id for job in jobs]

    async def get_contexts(self, job_ids: list[UUID]) -> list[PushDeliveryContext]:
        """Hydrate current tokens and payload identifiers for claimed jobs."""
        if not job_ids:
            return []
        result = await self.db.execute(
            select(
                PushDeliveryJob.id.label("job_id"),
                PushDeliveryJob.device_id,
                UserPushDevice.fcm_token,
                UserPushDevice.platform,
                StaleEstablishmentCycle.establishment_id,
                Establishment.name.label("establishment_name"),
                PushDeliveryJob.threshold_hours,
                PushDeliveryJob.attempt_count,
            )
            .join(UserPushDevice, UserPushDevice.id == PushDeliveryJob.device_id)
            .join(
                StaleEstablishmentCycle,
                StaleEstablishmentCycle.id == PushDeliveryJob.stale_cycle_id,
            )
            .join(
                Establishment,
                Establishment.id == StaleEstablishmentCycle.establishment_id,
            )
            .where(PushDeliveryJob.id.in_(job_ids))
            .order_by(PushDeliveryJob.id)
        )
        return [PushDeliveryContext(**row._mapping) for row in result.all()]

    async def delete_by_id(self, job_id: UUID) -> None:
        """Delete a successfully or terminally handled delivery job."""
        await self.db.execute(
            delete(PushDeliveryJob).where(PushDeliveryJob.id == job_id)
        )

    async def release_for_retry(self, job_id: UUID, *, available_at: datetime) -> None:
        """Increment retry count, clear the lease, and schedule another attempt."""
        result = await self.db.execute(
            select(PushDeliveryJob)
            .where(PushDeliveryJob.id == job_id)
            .with_for_update()
        )
        job = result.scalar_one_or_none()
        if job is not None:
            job.attempt_count += 1
            job.available_at = available_at
            job.claimed_until = None
