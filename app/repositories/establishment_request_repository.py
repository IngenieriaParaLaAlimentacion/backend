from uuid import UUID

from sqlalchemy import asc, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain.establishment import (
    EstablishmentCreationRequestListingParams,
    EstablishmentCreationRequestSortOrder,
)
from app.models.establishment_request import EstablishmentRequest
from app.models.user import User
from app.utils.db import escape_like, execute_paginated

# Maps each EstablishmentCreationRequestSortOrder value to its SQLAlchemy
# order clause. KeyError on an unmapped value is intentional: it surfaces
# missing cases immediately.
_SORT_CLAUSES = {
    EstablishmentCreationRequestSortOrder.NEWEST: desc(EstablishmentRequest.created_at),
    EstablishmentCreationRequestSortOrder.OLDEST: asc(EstablishmentRequest.created_at),
}


class EstablishmentRequestRepository:
    """Persistence operations for establishment creation requests."""

    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def _search_condition(search: str | None):
        """Case-insensitive match on the reported name/address or the
        requester's name, last name or email, or None for no search."""
        if not search:
            return None
        term = f"%{escape_like(search)}%"
        return (
            EstablishmentRequest.name.ilike(term, escape="\\")
            | EstablishmentRequest.formatted_address.ilike(term, escape="\\")
            | User.name.ilike(term, escape="\\")
            | User.last_name.ilike(term, escape="\\")
            | User.email.ilike(term, escape="\\")
        )

    @classmethod
    def _listing_conditions(
        cls, params: EstablishmentCreationRequestListingParams
    ) -> list:
        """Build the search/city/province/status filter conditions for a listing."""
        conditions = []
        search_condition = cls._search_condition(params.search)
        if search_condition is not None:
            conditions.append(search_condition)
        if params.city:
            term = f"%{escape_like(params.city)}%"
            conditions.append(EstablishmentRequest.city.ilike(term, escape="\\"))
        if params.province:
            term = f"%{escape_like(params.province)}%"
            conditions.append(EstablishmentRequest.province.ilike(term, escape="\\"))
        if params.status is not None:
            conditions.append(EstablishmentRequest.status == params.status)
        return conditions

    async def create(self, request: EstablishmentRequest) -> EstablishmentRequest:
        """Persist a new establishment creation request."""
        self.db.add(request)
        await self.db.flush()
        await self.db.refresh(request)
        return request

    async def get_by_id(self, request_id: UUID) -> EstablishmentRequest | None:
        """Return an establishment request by ID, or None if it does not exist."""
        return await self.db.get(EstablishmentRequest, request_id)

    async def get_paginated(
        self,
        limit: int,
        offset: int,
        params: EstablishmentCreationRequestListingParams,
    ) -> tuple[list[EstablishmentRequest], int]:
        """Return a paginated list of establishment creation requests and the
        total matching count, each with its requester eager-loaded.

        ``search`` matches case-insensitively against the reported
        name/address or the requester's name, last name or email. ``city``
        and ``province`` are partial, case-insensitive matches.
        ``status`` filters by review status.
        """
        base_query = (
            select(EstablishmentRequest)
            .join(User, EstablishmentRequest.user_id == User.id)
            .options(selectinload(EstablishmentRequest.user))
        )
        count_query = (
            select(func.count())
            .select_from(EstablishmentRequest)
            .join(User, EstablishmentRequest.user_id == User.id)
        )

        for condition in self._listing_conditions(params):
            base_query = base_query.where(condition)
            count_query = count_query.where(condition)

        order_by = _SORT_CLAUSES[params.sort_order]
        return await execute_paginated(
            self.db, base_query, count_query, order_by, limit, offset
        )
