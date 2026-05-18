from math import ceil

from app.repositories.establishment_repository import EstablishmentRepository
from app.schemas.establishment import (
    EstablishmentResponse,
    PaginatedEstablishmentsResponse,
)


class EstablishmentService:
    def __init__(self, establishment_repo: EstablishmentRepository):
        self.establishment_repository = establishment_repo

    async def get_establishments_paginated(
        self, page: int, page_size: int
    ) -> PaginatedEstablishmentsResponse:
        """Return a paginated response with establishments and pagination metadata."""

        offset = (page - 1) * page_size
        establishments, total = await self.establishment_repository.get_paginated(
            limit=page_size, offset=offset
        )
        total_pages = ceil(total / page_size) if total > 0 else 0

        return PaginatedEstablishmentsResponse(
            items=[EstablishmentResponse.model_validate(e) for e in establishments],
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )
