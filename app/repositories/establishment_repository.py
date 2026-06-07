from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions.domain_exceptions import EstablishmentNotFoundError
from app.models.establishment import Establishment
from app.utils.db import escape_like, execute_paginated


class EstablishmentRepository:
    """Persistence operations for Establishment entities."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, establishment: Establishment) -> Establishment:
        """Persist a new establishment."""
        self.db.add(establishment)
        await self.db.flush()
        await self.db.refresh(establishment)
        return establishment

    async def update(self, establishment: Establishment) -> Establishment:
        """Persist changes to an existing establishment."""
        await self.db.flush()
        await self.db.refresh(establishment)
        return establishment

    async def get_by_place_id(self, place_id: str) -> Establishment | None:
        """Return an establishment by place_id, or None if it does not exist."""
        result = await self.db.execute(
            select(Establishment).where(Establishment.place_id == place_id)
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, id: UUID) -> Establishment | None:
        """Return an establishment by ID, or None if it does not exist."""
        return await self.db.get(Establishment, id)

    async def find_by_ids(self, ids: list[UUID]) -> list[Establishment]:
        """Return establishments for the given IDs, silently skipping any
        that do not exist."""
        result = await self.db.execute(
            select(Establishment).where(Establishment.id.in_(ids))
        )
        return result.scalars().all()

    async def get_all_by_ids(self, ids: list[UUID]) -> list[Establishment]:
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
    ) -> tuple[list[Establishment], int]:
        """Return a paginated list of establishments and the total matching count.

        ``search`` matches case-insensitively against name or address (OR).
        """
        base_query = select(Establishment)
        count_query = select(func.count()).select_from(Establishment)

        if search:
            search_term = f"%{escape_like(search)}%"
            condition = Establishment.name.ilike(
                search_term, escape="\\"
            ) | Establishment.formatted_address.ilike(search_term, escape="\\")
            base_query = base_query.where(condition)
            count_query = count_query.where(condition)

        return await execute_paginated(
            self.db, base_query, count_query, Establishment.created_at, limit, offset
        )
