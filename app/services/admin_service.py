from math import ceil
from uuid import UUID

from app.core.interfaces.unit_of_work import IUnitOfWork
from app.domain.establishment import EstablishmentDomain
from app.domain.pagination import PaginatedResult
from app.domain.user import UserRole, UserStatus, UserWithEstablishmentsDomain


class AdminService:
    """Service layer for admin-related business logic."""

    def __init__(self, uow: IUnitOfWork) -> None:
        self.uow = uow

    async def _build_establishment_lookup_by_id(
        self, establishment_ids: list[UUID]
    ) -> dict[UUID, EstablishmentDomain]:
        """Return establishments keyed by id for fast lookup."""
        establishments = await self.uow.establishment_repo.get_by_ids(establishment_ids)
        return {
            establishment.id: EstablishmentDomain(
                id=establishment.id,
                name=establishment.name,
                address=establishment.address,
            )
            for establishment in establishments
        }

    async def _get_establishments_per_user(
        self, user_ids: list[UUID]
    ) -> dict[UUID, list[EstablishmentDomain]]:
        """Return the full establishment details for each user."""
        user_establishment_ids = await self.uow.user_establishment_repo.get_by_user_ids(
            user_ids
        )

        unique_establishment_ids = list(
            {
                establishment_id
                for establishment_ids in user_establishment_ids.values()
                for establishment_id in establishment_ids
            }
        )

        if not unique_establishment_ids:
            return {user_id: [] for user_id in user_ids}

        establishment_lookup = await self._build_establishment_lookup_by_id(
            unique_establishment_ids
        )

        result: dict[UUID, list[EstablishmentDomain]] = {}
        for user_id, establishment_ids in user_establishment_ids.items():
            result[user_id] = [
                establishment_lookup[establishment_id]
                for establishment_id in establishment_ids
                if establishment_id in establishment_lookup
            ]
        return result

    def _build_paginated_result(
        self,
        users: list,
        establishments_per_user: dict[UUID, list[EstablishmentDomain]],
        total: int,
        page: int,
        page_size: int,
    ) -> PaginatedResult[UserWithEstablishmentsDomain]:
        """Build a paginated response from users and their establishments."""
        items = [
            UserWithEstablishmentsDomain(
                id=user.id,
                email=user.email,
                name=user.name,
                last_name=user.last_name,
                role=user.role,
                status=user.status,
                establishments=establishments_per_user.get(user.id, []),
            )
            for user in users
        ]
        return PaginatedResult(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=ceil(total / page_size),
        )

    async def get_users_paginated(
        self,
        page: int,
        page_size: int,
        role: UserRole | None = None,
        status: UserStatus | None = None,
    ) -> PaginatedResult[UserWithEstablishmentsDomain]:
        """Return a paginated list of users with their establishments."""
        offset = (page - 1) * page_size
        users, total = await self.uow.user_repo.get_paginated(
            role=role, status=status, limit=page_size, offset=offset
        )

        if not users:
            return PaginatedResult(
                items=[],
                total=total,
                page=page,
                page_size=page_size,
                total_pages=0,
            )

        establishments_per_user = await self._get_establishments_per_user(
            [user.id for user in users]
        )

        return self._build_paginated_result(
            users=users,
            establishments_per_user=establishments_per_user,
            total=total,
            page=page,
            page_size=page_size,
        )
