from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.notifications import EstablishmentOutflowActivity
from app.models.food_outflows.food_outflow import FoodOutflow
from app.models.notifications.push_delivery_job import PushDeliveryJob
from app.models.notifications.stale_establishment_cycle import (
    StaleEstablishmentCycle,
)


class StaleEstablishmentCycleRepository:
    """Database operations for the current cycle of each establishment."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_activity_advances(self) -> list[EstablishmentOutflowActivity]:
        """Return absent cycles and strictly newer event-time maxima."""
        latest = (
            select(
                FoodOutflow.establishment_id.label("establishment_id"),
                func.max(FoodOutflow.occurred_at).label("last_outflow_at"),
            )
            .group_by(FoodOutflow.establishment_id)
            .subquery()
        )
        result = await self.db.execute(
            select(latest.c.establishment_id, latest.c.last_outflow_at)
            .outerjoin(
                StaleEstablishmentCycle,
                StaleEstablishmentCycle.establishment_id == latest.c.establishment_id,
            )
            .where(
                or_(
                    StaleEstablishmentCycle.id.is_(None),
                    latest.c.last_outflow_at > StaleEstablishmentCycle.last_outflow_at,
                )
            )
            .order_by(latest.c.establishment_id)
        )
        return [
            EstablishmentOutflowActivity(
                establishment_id=row.establishment_id,
                last_outflow_at=row.last_outflow_at,
            )
            for row in result.all()
        ]

    async def get_for_update(
        self, establishment_id: UUID
    ) -> StaleEstablishmentCycle | None:
        """Lock and return one establishment's current cycle."""
        result = await self.db.execute(
            select(StaleEstablishmentCycle)
            .where(StaleEstablishmentCycle.establishment_id == establishment_id)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def create_if_absent(
        self,
        *,
        establishment_id: UUID,
        last_outflow_at: datetime,
        started_at: datetime,
        next_threshold_hours: int,
        next_due_at: datetime,
    ) -> StaleEstablishmentCycle | None:
        """Insert and return a first cycle, or None if another runner won."""
        statement = (
            insert(StaleEstablishmentCycle)
            .values(
                establishment_id=establishment_id,
                last_outflow_at=last_outflow_at,
                started_at=started_at,
                next_threshold_hours=next_threshold_hours,
                next_due_at=next_due_at,
            )
            .on_conflict_do_nothing(
                constraint="uq_stale_establishment_cycles_establishment_id"
            )
            .returning(StaleEstablishmentCycle)
        )
        result = await self.db.execute(statement)
        return result.scalar_one_or_none()

    async def delete_pending_jobs(self, cycle_id: UUID) -> None:
        """Cancel all old-cycle jobs before resetting the current row."""
        await self.db.execute(
            delete(PushDeliveryJob).where(PushDeliveryJob.stale_cycle_id == cycle_id)
        )

    async def list_due_for_update(
        self,
        *,
        now: datetime,
        limit: int,
        after_due_at: datetime | None = None,
        after_id: UUID | None = None,
    ) -> list[StaleEstablishmentCycle]:
        """Lock one keyset page, allowing concurrent runners to skip it."""
        predicates = [
            StaleEstablishmentCycle.next_due_at.is_not(None),
            StaleEstablishmentCycle.next_due_at <= now,
        ]
        if after_due_at is not None and after_id is not None:
            predicates.append(
                or_(
                    StaleEstablishmentCycle.next_due_at > after_due_at,
                    and_(
                        StaleEstablishmentCycle.next_due_at == after_due_at,
                        StaleEstablishmentCycle.id > after_id,
                    ),
                )
            )
        result = await self.db.execute(
            select(StaleEstablishmentCycle)
            .where(*predicates)
            .order_by(
                StaleEstablishmentCycle.next_due_at,
                StaleEstablishmentCycle.id,
            )
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return list(result.scalars().all())
