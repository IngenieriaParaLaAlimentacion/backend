from typing import List
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.establishment import Establishment


class EstablishmentRepository:
    """Persistence operations for Establishment entities."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_all(self) -> List[Establishment]:
        """Return all establishments."""
        result = await self.db.execute(select(Establishment))
        return list(result.scalars().all())

    async def get_by_ids(self, ids: List[UUID]) -> List[Establishment]:
        """Return only the establishments whose id is in the given list."""
        result = await self.db.execute(
            select(Establishment).where(Establishment.id.in_(ids))
        )
        return list(result.scalars().all())
