import uuid
from typing import List, Tuple
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.establishment import Establishment


class EstablishmentRepository:
    """Persistence operations for Establishment entities."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, id: uuid.UUID) -> Establishment | None:
        """Return an establishment by ID, or None if it does not exist."""
        result = await self.db.execute(
            select(Establishment).where(Establishment.id == id)
        )
        return result.scalar_one_or_none()

    async def get_by_ids(self, ids: List[UUID]) -> List[Establishment]:
        """Return only the establishments whose id is in the given list."""
        result = await self.db.execute(
            select(Establishment).where(Establishment.id.in_(ids))
        )
        return list(result.scalars().all())

    async def get_paginated(
        self, limit: int, offset: int
    ) -> Tuple[List[Establishment], int]:
        """Retrieve a paginated list of establishments along with the total count."""
        count_query = select(func.count()).select_from(Establishment)
        establishments_query = (
            select(Establishment).order_by(Establishment.id).limit(limit).offset(offset)
        )

        total = (await self.db.execute(count_query)).scalar_one()
        establishments = (await self.db.execute(establishments_query)).scalars().all()

        return list(establishments), total
