from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.measurement import AlertSeverity, AlertType
from app.models.measurements.measurement_alert import MeasurementAlert


class MeasurementAlertRepository:
    """Persistence operations for MeasurementAlert entities."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_bulk(
        self,
        measurement_id: UUID,
        alerts: list[tuple[AlertType, AlertSeverity, str]],
    ) -> list[MeasurementAlert]:
        """Persist a batch of alerts for a single measurement."""
        rows = [
            MeasurementAlert(
                measurement_id=measurement_id,
                alert_type=alert_type,
                severity=severity,
                detail=detail,
            )
            for alert_type, severity, detail in alerts
        ]
        self.db.add_all(rows)
        await self.db.flush()
        return rows

    async def get_by_measurement_id(
        self, measurement_id: UUID
    ) -> list[MeasurementAlert]:
        """Return all alerts for the given measurement."""
        result = await self.db.execute(
            select(MeasurementAlert).where(
                MeasurementAlert.measurement_id == measurement_id
            )
        )
        return list(result.scalars().all())
