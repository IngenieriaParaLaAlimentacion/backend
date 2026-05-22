from math import ceil
from uuid import UUID

from app.core.interfaces.unit_of_work import IUnitOfWork
from app.domain.establishment import EstablishmentDomain, EstablishmentWithStatusDomain
from app.domain.pagination import PaginatedResult
from app.domain.user import (
    ApprovedManagerDomain,
    UserRole,
    UserStatus,
    UserWithEstablishmentsDomain,
)
from app.exceptions.domain_exceptions import (
    UserEstablishmentNotFoundError,
    UserNotFoundError,
)


class AdminService:
    """Service layer for admin-related business logic."""

    def __init__(self, uow: IUnitOfWork) -> None:
        self.uow = uow

    async def _build_establishments_data(
        self, establishment_ids: list[UUID]
    ) -> dict[UUID, EstablishmentDomain]:
        """Return establishments keyed by id for fast lookup."""
        establishments = await self.uow.establishment_repo.find_by_ids(
            establishment_ids
        )
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
        estab_ids_by_user: dict[
            UUID, list[UUID]
        ] = await self.uow.user_establishment_repo.get_by_user_ids(user_ids)

        unique_establishment_ids = list(
            {e_id for ids in estab_ids_by_user.values() for e_id in ids}
        )

        if not unique_establishment_ids:
            return {user_id: [] for user_id in user_ids}

        establishments_data: dict[
            UUID, EstablishmentDomain
        ] = await self._build_establishments_data(unique_establishment_ids)

        estab_data_by_user: dict[UUID, list[EstablishmentDomain]] = {}
        for user_id, establishment_ids in estab_ids_by_user.items():
            estab_data_by_user[user_id] = [
                establishments_data[e_id] for e_id in establishment_ids
            ]
        return estab_data_by_user

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

    async def approve_manager(
        self, user_id: UUID, approved_ids: list[UUID]
    ) -> ApprovedManagerDomain:
        """Approve a manager and set the status of each of their establishments."""
        user = await self.uow.user_repo.get_by_id(user_id)
        if user is None:
            raise UserNotFoundError(str(user_id))

        relations = await self.uow.user_establishment_repo.get_by_user_id(user_id)
        user_establishment_ids = {rel.establishment_id for rel in relations}

        approved_set = set(approved_ids)
        invalid_ids = approved_set - user_establishment_ids
        if invalid_ids:
            raise UserEstablishmentNotFoundError(
                str(next(iter(invalid_ids))), str(user_id)
            )

        establishments = await self.uow.establishment_repo.find_by_ids(
            list(user_establishment_ids)
        )

        await self.uow.user_repo.update_status(user_id, UserStatus.ACTIVE)
        await self.uow.user_establishment_repo.update_statuses(
            user_id, list(approved_set)
        )
        await self.uow.commit()

        approved_set = set(approved_ids)
        return ApprovedManagerDomain(
            id=user.id,
            email=user.email,
            name=user.name,
            last_name=user.last_name,
            role=user.role,
            status=UserStatus.ACTIVE,
            establishments=[
                EstablishmentWithStatusDomain(
                    id=estab.id,
                    name=estab.name,
                    address=estab.address,
                    status="approved" if estab.id in approved_set else "rejected",
                )
                for estab in establishments
            ],
        )
