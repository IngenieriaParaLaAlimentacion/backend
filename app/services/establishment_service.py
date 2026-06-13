from uuid import UUID

from app.core.interfaces.unit_of_work import IUnitOfWork
from app.domain.establishment import EstablishmentDomain
from app.domain.pagination import PaginatedResult


class EstablishmentService:
    """Service layer for establishment queries."""

    def __init__(
        self,
        uow: IUnitOfWork,
    ):
        self.uow = uow

    async def get_establishments_paginated(
        self,
        page: int,
        page_size: int,
        search: str | None,
    ) -> PaginatedResult[EstablishmentDomain]:
        """Return a paginated list of establishments with metadata.

        ``search`` matches case-insensitively against name or address.
        Whitespace-only values are treated as no filter.
        """
        offset = (page - 1) * page_size
        search = search.strip() or None if search else None
        establishments, total = await self.uow.establishment_repo.get_paginated(
            limit=page_size, offset=offset, search=search
        )
        return PaginatedResult.build(
            items=[
                EstablishmentDomain(
                    id=establishment.id,
                    name=establishment.name,
                    address=establishment.address,
                )
                for establishment in establishments
            ],
            total=total,
            page=page,
            page_size=page_size,
        )

    async def get_available_establishments(
        self,
        user_id: UUID,
        page: int,
        page_size: int,
        search: str | None,
    ) -> PaginatedResult[EstablishmentDomain]:
        """Return establishments the user can still request, paginated."""
        offset = (page - 1) * page_size
        search = search.strip() or None if search else None
        (
            establishments,
            total,
        ) = await self.uow.establishment_repo.get_available_for_user(
            user_id=user_id, limit=page_size, offset=offset, search=search
        )
        return PaginatedResult.build(
            items=[
                EstablishmentDomain(
                    id=establishment.id,
                    name=establishment.name,
                    address=establishment.address,
                )
                for establishment in establishments
            ],
            total=total,
            page=page,
            page_size=page_size,
        )
