import hashlib
from datetime import date
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.nutrition.nutrition_report import NutritionReport


class NutritionReportRepository:
    """Persist the monthly nutrition reports of the establishments."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_month(
        self, establishment_id: UUID, month: date
    ) -> NutritionReport | None:
        """Return the report of an establishment for the month starting on ``month``."""
        result = await self.db.execute(
            select(NutritionReport).where(
                NutritionReport.establishment_id == establishment_id,
                NutritionReport.month == month,
            )
        )
        return result.scalar_one_or_none()

    async def create(self, report: NutritionReport) -> NutritionReport:
        """Stage a new report for insertion."""
        self.db.add(report)
        await self.db.flush()
        return report

    async def update(self, report: NutritionReport) -> NutritionReport:
        """Persist changes made to an existing report."""
        await self.db.flush()
        # The database sets updated_at, which leaves it expired for the caller.
        await self.db.refresh(report)
        return report

    async def lock(self, establishment_id: UUID, month: date) -> None:
        """Make other transactions wait until this one ends before taking the same
        report's lock."""
        # A row lock cannot protect a report that has not been inserted yet.
        digest = hashlib.blake2b(
            f"{establishment_id}:{month.isoformat()}".encode(),
            digest_size=8,
            # Keeps these keys apart from other advisory locks in the database.
            person=b"nutrition_report",
        ).digest()
        key = int.from_bytes(digest, "big", signed=True)
        await self.db.execute(select(func.pg_advisory_xact_lock(key)))
