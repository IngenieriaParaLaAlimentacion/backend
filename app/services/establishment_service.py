from math import ceil

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
        self, page: int, page_size: int
    ) -> PaginatedResult[EstablishmentDomain]:
        """Return a paginated result with establishments and pagination metadata."""

        offset = (page - 1) * page_size
        establishments, total = await self.uow.establishment_repo.get_paginated(
            limit=page_size, offset=offset
        )
        total_pages = ceil(total / page_size) if total > 0 else 0

        return PaginatedResult(
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
            total_pages=total_pages,
        )
