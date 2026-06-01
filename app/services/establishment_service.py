from math import ceil
from uuid import UUID

from app.core.interfaces.unit_of_work import IUnitOfWork
from app.domain.establishment import EstablishmentDomain
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

    async def create_establishment(self, data: EstablishmentRequest, actor_id: UUID):
        """Register a new establishment.

        Raises:
            EstablishmentAlreadyExistsError: If an establishment with the name
            and address already exists.
        """
        establishment = await self.uow.establishment_repo.get_by_data(
            data.name, data.address
        )
        if establishment:
            raise EstablishmentAlreadyExistsError(data.name, data.address)

        establishment = await self.uow.establishment_repo.create(
            name=data.name, address=data.address
        )
        await self.uow.commit()
        return establishment

    async def update_establishment(
        self, establishment_id: UUID, data: EstablishmentUpdateRequest
    ) -> Establishment:
        """Apply a partial update to an existing establishment.

        Raises:
            EstablishmentNotFoundError: If no establishment with that ID exists.
            EstablishmentAlreadyExistsError: If the resulting name+address is
            already taken by a different establishment.
        """
        establishment = await self.uow.establishment_repo.get_by_id(establishment_id)
        if establishment is None:
            raise EstablishmentNotFoundError(str(establishment_id))

        new_name = data.name if data.name is not None else establishment.name
        new_address = (
            data.address if data.address is not None else establishment.address
        )

        duplicate = await self.uow.establishment_repo.get_by_data(new_name, new_address)
        if duplicate is not None and duplicate.id != establishment.id:
            raise EstablishmentAlreadyExistsError(new_name, new_address)

        establishment = await self.uow.establishment_repo.update(
            establishment, name=data.name, address=data.address
        )
        await self.uow.commit()
        return establishment

    async def get_establishment_by_id(self, establishment_id: UUID) -> Establishment:
        """Return an establishment by ID.

        Raises:
            EstablishmentNotFoundError: If no establishment with that ID exists.
        """
        establishment = await self.uow.establishment_repo.get_by_id(establishment_id)
        if establishment is None:
            raise EstablishmentNotFoundError(str(establishment_id))
        return establishment

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
