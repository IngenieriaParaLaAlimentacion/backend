import uuid
from typing import List, Tuple
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions.domain_exceptions import EstablishmentNotFoundError
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

    async def find_by_ids(self, ids: List[UUID]) -> List[Establishment]:
        """Return establishments for the given IDs, silently skipping any
        that do not exist."""
        result = await self.db.execute(
            select(Establishment).where(Establishment.id.in_(ids))
        )
        return result.scalars().all()

    async def get_all_by_ids(self, ids: List[UUID]) -> List[Establishment]:
        """Return establishments for all given IDs.

        Raises:
            EstablishmentNotFoundError: if any of the requested establishment
            is missing.
        """
        establishments = await self.find_by_ids(ids)
        id_set = set(ids)

        if len(establishments) != len(id_set):
            found_ids = {establishment.id for establishment in establishments}
            missing = next(iter(id_set - found_ids))
            raise EstablishmentNotFoundError(str(missing))

        return establishments

    async def get_paginated(
        self,
        limit: int,
        offset: int,
        search: str | None = None,
    ) -> Tuple[List[Establishment], int]:
        """Return a paginated list of establishments and the total matching count.

        Optional free-text filter applied case-insensitively against name and address
        (OR match). Special SQL wildcard characters are escaped before use.
        """
        base_query = select(Establishment)
        count_query = select(func.count()).select_from(Establishment)

        if search:
            escaped = (
                search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            )
            search_term = f"%{escaped}%"
            condition = Establishment.name.ilike(
                search_term, escape="\\"
            ) | Establishment.address.ilike(search_term, escape="\\")
            base_query = base_query.where(condition)
            count_query = count_query.where(condition)

        establishments_query = (
            base_query.order_by(Establishment.id).limit(limit).offset(offset)
        )

        total = (await self.db.execute(count_query)).scalar_one()
        establishments = (await self.db.execute(establishments_query)).scalars().all()

        return establishments, total
