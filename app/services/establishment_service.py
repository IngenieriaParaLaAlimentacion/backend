from uuid import UUID

from app.core.interfaces.unit_of_work import IUnitOfWork
from app.domain.establishment import EstablishmentDomain, EstablishmentListingParams
from app.domain.pagination import PaginatedResult
from app.exceptions.domain_exceptions import (
    EstablishmentAlreadyExistsError,
    EstablishmentNotFoundError,
)
from app.models import Establishment
from app.schemas.establishment_schema import (
    EstablishmentRequest,
    EstablishmentUpdateRequest,
)


class EstablishmentService:
    """Service layer for establishment queries."""

    def __init__(
        self,
        uow: IUnitOfWork,
    ):
        self.uow = uow

    async def create_establishment(
        self, data: EstablishmentRequest
    ) -> EstablishmentDomain:
        """Register a new establishment.

        Raises:
            EstablishmentAlreadyExistsError: If an establishment with the same
                place_id already exists.
        """
        existing = await self.uow.establishment_repo.get_by_place_id(data.place_id)
        if existing:
            raise EstablishmentAlreadyExistsError(data.place_id)

        establishment = await self.uow.establishment_repo.create(
            Establishment(**data.model_dump())
        )
        await self.uow.commit()
        return EstablishmentDomain.from_db(establishment)

    async def update_establishment(
        self, establishment_id: UUID, data: EstablishmentUpdateRequest
    ) -> EstablishmentDomain:
        """Apply a partial update to an existing establishment.

        Raises:
            EstablishmentNotFoundError: If no establishment with that ID exists.
            EstablishmentAlreadyExistsError: If the new place_id is already
                taken by a different establishment.
        """
        establishment = await self.uow.establishment_repo.get_by_id(establishment_id)
        if establishment is None:
            raise EstablishmentNotFoundError(str(establishment_id))

        if data.place_id is not None:
            duplicate = await self.uow.establishment_repo.get_by_place_id(data.place_id)
            if duplicate is not None and duplicate.id != establishment.id:
                raise EstablishmentAlreadyExistsError(data.place_id)

        for field, value in data.model_dump(exclude_none=True).items():
            if getattr(establishment, field) != value:
                setattr(establishment, field, value)

        establishment = await self.uow.establishment_repo.update(establishment)
        await self.uow.commit()
        return EstablishmentDomain.from_db(establishment)

    async def get_establishment_by_id(
        self, establishment_id: UUID
    ) -> EstablishmentDomain:
        """Return an establishment by ID.

        Raises:
            EstablishmentNotFoundError: If no establishment with that ID exists.
        """
        establishment = await self.uow.establishment_repo.get_by_id(establishment_id)
        if establishment is None:
            raise EstablishmentNotFoundError(str(establishment_id))
        return EstablishmentDomain.from_db(establishment)

    async def get_establishments_paginated(
        self,
        page: int,
        page_size: int,
        params: EstablishmentListingParams,
    ) -> PaginatedResult[EstablishmentDomain]:
        """Return a paginated list of establishments with metadata.

        ``search`` matches case-insensitively against name or address.
        ``city`` and ``province`` are exact case-insensitive matches.
        Whitespace-only values are treated as no filter.
        """
        offset = (page - 1) * page_size
        params.search = params.search.strip() or None if params.search else None
        params.city = params.city.strip() or None if params.city else None
        params.province = params.province.strip() or None if params.province else None
        establishments, total = await self.uow.establishment_repo.get_paginated(
            limit=page_size, offset=offset, params=params
        )
        return PaginatedResult.build(
            items=[EstablishmentDomain.from_db(e) for e in establishments],
            total=total,
            page=page,
            page_size=page_size,
        )
