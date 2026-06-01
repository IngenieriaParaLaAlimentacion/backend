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

    async def create(
        self,
        name: str,
        address: str,
    ) -> Establishment:
        """Persist a new establishment."""
        establishment = Establishment(
            name=name,
            address=address,
        )
        self.db.add(establishment)
        await self.db.flush()
        await self.db.refresh(establishment)
        return establishment

    async def update(
        self,
        establishment: Establishment,
        name: str | None,
        address: str | None,
    ) -> Establishment:
        """Apply partial updates to an existing establishment."""
        if name is not None:
            establishment.name = name
        if address is not None:
            establishment.address = address
        await self.db.flush()
        await self.db.refresh(establishment)
        return establishment

    async def get_by_data(self, name: str, address: str) -> Establishment | None:
        """Return an establishment by name and address, or None if it does not exist."""
        result = await self.db.execute(
            select(Establishment).where(
                Establishment.name == name, Establishment.address == address
            )
        )
        return result.scalar_one_or_none()

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

        ``search`` matches case-insensitively against name or address (OR).
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
