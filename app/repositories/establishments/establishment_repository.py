from uuid import UUID

from sqlalchemy import asc, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.establishment import (
    EstablishmentListingParams,
    EstablishmentSortOrder,
    UserEstablishmentStatus,
)
from app.exceptions.domain_exceptions import EstablishmentNotFoundError
from app.models.auth.user_establishment import UserEstablishment
from app.models.establishments.establishment import Establishment
from app.utils.db import execute_paginated, ilike_condition, insert_with_savepoint

# Maps each EstablishmentSortOrder value to its SQLAlchemy order clause.
# KeyError on an unmapped value is intentional: it surfaces missing cases immediately.
_SORT_CLAUSES = {
    EstablishmentSortOrder.NEWEST: desc(Establishment.created_at),
    EstablishmentSortOrder.OLDEST: asc(Establishment.created_at),
    EstablishmentSortOrder.NAME_ASC: asc(Establishment.name),
    EstablishmentSortOrder.NAME_DESC: desc(Establishment.name),
    EstablishmentSortOrder.CITY_ASC: asc(Establishment.city),
    EstablishmentSortOrder.CITY_DESC: desc(Establishment.city),
    EstablishmentSortOrder.PROVINCE_ASC: asc(Establishment.province),
    EstablishmentSortOrder.PROVINCE_DESC: desc(Establishment.province),
}


class EstablishmentRepository:
    """Persistence operations for Establishment entities."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, establishment: Establishment) -> Establishment:
        """Persist a new establishment.

        The insert runs inside a SAVEPOINT so a unique violation rolls back
        only the failed row and leaves the session usable for the caller to
        re-query.

        Raises:
            UniqueConstraintError: If place_id is already in use. The caller
                is responsible for re-querying to decide the outcome.
        """
        return await insert_with_savepoint(
            self.db, establishment, "place_id", establishment.place_id
        )

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

    async def get_by_id_or_raise(self, id: UUID) -> Establishment:
        """Return an establishment by ID.

        Callers that resolve an establishment before doing any work use this so
        an unknown id answers 404 rather than an empty result, which would be
        indistinguishable from a real establishment with no data.

        Raises:
            EstablishmentNotFoundError: if the establishment does not exist.
        """
        establishment = await self.get_by_id(id)
        if establishment is None:
            raise EstablishmentNotFoundError(str(id))
        return establishment

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

    @staticmethod
    def _search_condition(search: str | None):
        """Case-insensitive name/formatted_address match for ``search``, or None.

        Returns None when ``search`` is empty so callers can skip the filter.
        """
        if not search:
            return None
        return or_(
            ilike_condition(Establishment.name, search),
            ilike_condition(Establishment.formatted_address, search),
        )

    @staticmethod
    def _append_ilike(conditions: list, column, value: str | None) -> None:
        """Append a partial match condition for column to conditions, if given."""
        if value:
            conditions.append(ilike_condition(column, value))

    @classmethod
    def _listing_conditions(cls, params: EstablishmentListingParams) -> list:
        """Build the search/city/province filter conditions for a listing."""
        conditions = []
        search_condition = cls._search_condition(params.search)
        if search_condition is not None:
            conditions.append(search_condition)
        cls._append_ilike(conditions, Establishment.city, params.city)
        cls._append_ilike(conditions, Establishment.province, params.province)
        return conditions

    async def get_paginated(
        self,
        limit: int,
        offset: int,
        params: EstablishmentListingParams,
    ) -> tuple[list[Establishment], int]:
        """Return a paginated list of establishments and the total matching count.

        ``search`` matches case-insensitively against name or formatted_address.
        ``city`` and ``province`` are partial, case-insensitive matches.
        """
        base_query = select(Establishment)
        count_query = select(func.count()).select_from(Establishment)

        order_by = _SORT_CLAUSES[params.sort_order]
        return await execute_paginated(
            self.db,
            base_query,
            count_query,
            order_by,
            limit,
            offset,
            conditions=self._listing_conditions(params),
        )

    async def get_available_for_user(
        self,
        user_id: UUID,
        limit: int,
        offset: int,
        params: EstablishmentListingParams,
    ) -> tuple[list[Establishment], int]:
        """Return establishments the user can still request access to, paginated.

        Excludes establishments where the user already has an ``approved`` or
        ``pending`` relation; ``rejected`` relations are treated as available
        (re-requestable). Applies the same search/city/province/sort filters as
        ``get_paginated``.
        """
        blocked = select(UserEstablishment.establishment_id).where(
            UserEstablishment.user_id == user_id,
            UserEstablishment.status.in_(
                [UserEstablishmentStatus.APPROVED, UserEstablishmentStatus.PENDING]
            ),
        )
        base_query = select(Establishment).where(Establishment.id.not_in(blocked))
        count_query = (
            select(func.count())
            .select_from(Establishment)
            .where(Establishment.id.not_in(blocked))
        )

        order_by = _SORT_CLAUSES[params.sort_order]
        return await execute_paginated(
            self.db,
            base_query,
            count_query,
            order_by,
            limit,
            offset,
            conditions=self._listing_conditions(params),
        )
