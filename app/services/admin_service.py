from math import ceil
from uuid import UUID

from app.core.interfaces.unit_of_work import IUnitOfWork
from app.domain.establishment import EstablishmentDomain, UserEstablishmentStatus
from app.domain.pagination import PaginatedResult
from app.domain.subject import SubjectDomain
from app.domain.subject_event import SubjectEventRecord
from app.domain.user import (
    UserRole,
    UserStatus,
    UserWithEstablishmentsDomain,
)
from app.exceptions.domain_exceptions import (
    SubjectNotFoundError,
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
        search: str | None = None,
    ) -> PaginatedResult[UserWithEstablishmentsDomain]:
        """Return a paginated list of users with their establishments.

        ``search`` matches case-insensitively against email, name, and last_name.
        Whitespace-only values are treated as no filter.
        """
        offset = (page - 1) * page_size
        search = search.strip() or None if search else None

        users, total = await self.uow.user_repo.get_paginated(
            role=role, status=status, limit=page_size, offset=offset, search=search
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

    async def _validate_access_request(
        self, user_id: UUID, establishment_ids: list[UUID]
    ) -> None:
        """Validate that the user exists and all establishment IDs belong to them."""
        user = await self.uow.user_repo.get_by_id(user_id)
        if user is None:
            raise UserNotFoundError(str(user_id))

        relations = await self.uow.user_establishment_repo.get_by_user_id(user_id)
        user_establishment_ids = {rel.establishment_id for rel in relations}

        invalid_ids = set(establishment_ids) - user_establishment_ids
        if invalid_ids:
            raise UserEstablishmentNotFoundError(
                str(next(iter(invalid_ids))), str(user_id)
            )

    async def _set_user_establishment_relation_status(
        self,
        user_id: UUID,
        establishment_ids: list[UUID],
        status: UserEstablishmentStatus,
    ) -> None:
        """Validate and write a status update for the given user-establishment pairs."""
        await self._validate_access_request(user_id, establishment_ids)
        await self.uow.user_establishment_repo.update_status_for_ids(
            user_id, establishment_ids, status
        )

    async def approve_establishments(
        self, user_id: UUID, establishment_ids: list[UUID]
    ) -> None:
        """Approve access to the given establishments and activate the manager."""
        await self._set_user_establishment_relation_status(
            user_id, establishment_ids, UserEstablishmentStatus.APPROVED
        )
        await self.uow.user_repo.update_status(user_id, UserStatus.ACTIVE)
        await self.uow.commit()

    async def reject_establishments(
        self, user_id: UUID, establishment_ids: list[UUID]
    ) -> None:
        """Reject access to the given establishments. Does not change user status."""
        await self._set_user_establishment_relation_status(
            user_id, establishment_ids, UserEstablishmentStatus.REJECTED
        )
        await self.uow.commit()

    async def get_subject_detail(
        self,
        subject_id: UUID,
        *,
        history_page: int = 1,
        history_page_size: int = 20,
    ) -> tuple[SubjectDomain, PaginatedResult[SubjectEventRecord]]:
        """Return a subject and its paginated event history.

        Raises:
            SubjectNotFoundError: If no subject with the given id exists.
        """
        subject = await self.uow.subject_repo.get_by_id(subject_id)
        if subject is None:
            raise SubjectNotFoundError(str(subject_id))

        events, total = await self.uow.subject_event_repo.get_history(
            subject_id, page=history_page, page_size=history_page_size
        )
        history = PaginatedResult.build(
            items=[SubjectEventRecord.from_db(event) for event in events],
            total=total,
            page=history_page,
            page_size=history_page_size,
        )
        return SubjectDomain.from_db(subject), history
