from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.measurement import Measurement


class MeasurementRepository:
    """Persistence operations for Measurement entities."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_idempotency_key(self, key: UUID) -> Measurement | None:
        """Return the measurement matching the given idempotency key, or None."""
        result = await self.db.execute(
            select(Measurement).where(Measurement.idempotency_key == key)
        )
        return result.scalar_one_or_none()

    async def upsert_by_idempotency_key(
        self,
        idempotency_key: UUID,
        subject_id: UUID,
        responsible_id: UUID,
        establishment_id: UUID,
        weight_kg: float,
        height_cm: float,
        bmi: float,
        measured_at: datetime,
    ) -> tuple[Measurement, bool]:
        """Return (measurement, is_new). Inserts only when the key is unseen."""
        existing = await self.get_by_idempotency_key(idempotency_key)
        if existing is not None:
            return existing, False

        measurement = Measurement(
            idempotency_key=idempotency_key,
            subject_id=subject_id,
            responsible_id=responsible_id,
            establishment_id=establishment_id,
            weight_kg=weight_kg,
            height_cm=height_cm,
            bmi=bmi,
            measured_at=measured_at,
        )
        self.db.add(measurement)
        await self.db.flush()
        await self.db.refresh(measurement)
        return measurement, True
