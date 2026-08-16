from uuid import UUID

from sqlalchemy import asc, desc, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import contains_eager

from app.domain.establishment import (
    EstablishmentCreationRequestListingParams,
    EstablishmentCreationRequestSortOrder,
    EstablishmentRequestStatus,
)
from app.exceptions.domain_exceptions import (
    EstablishmentRequestAlreadyReviewedError,
    EstablishmentRequestNotFoundError,
)
from app.models.auth.user import User
from app.models.establishments.establishment_request import EstablishmentRequest
from app.utils.db import execute_paginated, ilike_condition

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
        return or_(
            ilike_condition(EstablishmentRequest.name, search),
            ilike_condition(EstablishmentRequest.formatted_address, search),
            ilike_condition(User.name, search),
            ilike_condition(User.last_name, search),
            ilike_condition(User.email, search),
        )

    @staticmethod
    def _append_ilike(conditions: list, column, value: str | None) -> None:
        """Append a partial match condition for column to conditions,
        if value is given."""
        if value:
            conditions.append(ilike_condition(column, value))

    @classmethod
    def _listing_conditions(
        cls, params: EstablishmentCreationRequestListingParams
    ) -> list:
        """Build the search/city/province/status filter conditions for a listing."""
        conditions = []
        search_condition = cls._search_condition(params.search)
        if search_condition is not None:
            conditions.append(search_condition)
        cls._append_ilike(conditions, EstablishmentRequest.city, params.city)
        cls._append_ilike(conditions, EstablishmentRequest.province, params.province)
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

    async def mark_reviewed_or_raise(
        self,
        request_id: UUID,
        status: EstablishmentRequestStatus,
        reviewer_id: UUID,
    ) -> EstablishmentRequest:
        """Atomically transition a pending request to ``status``, recording
        the reviewer.

        The ``WHERE status = pending`` condition is what makes this atomic:
        concurrent reviews of the same request can't both succeed.

        Raises:
            EstablishmentRequestNotFoundError: If no request with that ID
                exists.
            EstablishmentRequestAlreadyReviewedError: If it was not pending.
        """
        result = await self.db.execute(
            update(EstablishmentRequest)
            .where(
                EstablishmentRequest.id == request_id,
                EstablishmentRequest.status == EstablishmentRequestStatus.PENDING,
            )
            .values(status=status, reviewed_by=reviewer_id)
            .returning(EstablishmentRequest)
        )
        request = result.scalar_one_or_none()
        if request is not None:
            return request
        existing = await self.get_by_id(request_id)
        if existing is None:
            raise EstablishmentRequestNotFoundError(str(request_id))
        raise EstablishmentRequestAlreadyReviewedError(str(request_id))

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
            .options(contains_eager(EstablishmentRequest.user))
        )
        count_query = (
            select(func.count())
            .select_from(EstablishmentRequest)
            .join(User, EstablishmentRequest.user_id == User.id)
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
