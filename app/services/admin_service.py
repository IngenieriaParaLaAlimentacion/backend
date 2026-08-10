import secrets
from typing import Any
from uuid import UUID

from app.core.config import settings
from app.core.interfaces.unit_of_work import IUnitOfWork
from app.core.security import hash_password
from app.domain.establishment import EstablishmentDomain, UserEstablishmentStatus
from app.domain.pagination import PaginatedResult
from app.domain.subject import SubjectDomain
from app.domain.subject_event import SubjectEventRecord
from app.domain.user import (
    BACKOFFICE_ROLES,
    UserRole,
    UserStatus,
    UserWithEstablishmentsDomain,
)
from app.exceptions.domain_exceptions import (
    BadRequestError,
    ForbiddenError,
    SubjectNotFoundError,
    UserAlreadyExistsError,
    UserEstablishmentNotFoundError,
    UserNotFoundError,
)
from app.models.user import User
from app.schemas.admin_schema import InviteAdminRequest
from app.services.auth_service import AuthService
from app.services.email_service import (
    build_invite_deeplink,
    send_access_granted_email,
    send_invite_email,
)


class AdminService:
    """Service layer for admin-related business logic."""

    def __init__(self, uow: IUnitOfWork, auth_service: AuthService) -> None:
        self.uow = uow
        self.auth_service = auth_service

    async def _build_establishments_data(
        self, establishment_ids: list[UUID]
    ) -> dict[UUID, EstablishmentDomain]:
        """Return establishments keyed by id for fast lookup."""
        establishments = await self.uow.establishment_repo.find_by_ids(
            establishment_ids
        )
        return {
            establishment.id: EstablishmentDomain.from_db(establishment)
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

    async def _get_field_worker_relations(self, user_id: UUID) -> tuple[Any, list]:
        """Return (user, relations) for a field worker, raising if the user does
        not exist or their email is not yet verified."""
        user = await self.uow.user_repo.get_by_id(user_id)
        if user is None:
            raise UserNotFoundError(str(user_id))
        if settings.environment != "development" and not user.is_email_verified:
            raise ForbiddenError(
                "Email not verified",
                "The user's email has not been verified yet.",
            )
        relations = await self.uow.user_establishment_repo.get_by_user_id(user_id)
        return user, relations

    async def _validate_access_request(
        self, user_id: UUID, establishment_ids: list[UUID]
    ) -> None:
        """Validate that all establishment IDs belong to the field worker."""
        _, relations = await self._get_field_worker_relations(user_id)
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

    async def _issue_and_send_invite(self, user: User) -> None:
        """Generate a fresh recovery token for `user` and email the invite
        deeplink. Shared by invite_user and resend_invite.

        Raises:
            BadRequestError: If the user's role is not a backoffice role.
            EmailDeliveryError: If the invitation email could not be delivered.
        """
        if user.role not in BACKOFFICE_ROLES:
            raise BadRequestError("Invalid user role")

        created_token, plain_token = await self.auth_service.create_recovery_token(
            user.id
        )
        await self.uow.commit()
        await send_invite_email(
            user.email,
            build_invite_deeplink(plain_token, user.role),
            created_token.expires_at,
            user.role,
        )

    async def _build_paginated_users_result(
        self, users: list[User], total: int, page: int, page_size: int
    ) -> PaginatedResult[UserWithEstablishmentsDomain]:
        """Hydrate establishments for `users` and wrap them in a PaginatedResult."""
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

        return PaginatedResult.build(
            items=[
                UserWithEstablishmentsDomain.from_db(
                    user, establishments_per_user.get(user.id, [])
                )
                for user in users
            ],
            total=total,
            page=page,
            page_size=page_size,
        )

    async def approve_establishments(
        self, user_id: UUID, establishment_ids: list[UUID]
    ) -> None:
        """Approve access to the given establishments and activate the field worker."""
        await self._set_user_establishment_relation_status(
            user_id, establishment_ids, UserEstablishmentStatus.APPROVED
        )
        await self.uow.user_repo.update_status(user_id, UserStatus.ACTIVE)
        await self.uow.commit()

        user = await self.uow.user_repo.get_by_id(user_id)
        establishments = await self.uow.establishment_repo.find_by_ids(
            establishment_ids
        )
        await send_access_granted_email(
            user.email,
            [e.name for e in establishments],
        )

    async def reject_establishments(
        self, user_id: UUID, establishment_ids: list[UUID]
    ) -> None:
        """Reject access to the given establishments. Does not change user status."""
        await self._set_user_establishment_relation_status(
            user_id, establishment_ids, UserEstablishmentStatus.REJECTED
        )
        await self.uow.commit()

    async def reject_field_worker(self, user_id: UUID) -> None:
        """Reject all establishment access for the given field worker and
        mark them inactive.

        Raises:
            UserNotFoundError: If the user does not exist.
            BadRequestError: If the field worker is not in pending status.
        """
        user, relations = await self._get_field_worker_relations(user_id)
        if user.status != UserStatus.PENDING_VALIDATION:
            raise BadRequestError(
                "Field worker is not pending",
                "Only field workers with pending status can be rejected through "
                "this endpoint.",
            )
        establishment_ids = [rel.establishment_id for rel in relations]

        if establishment_ids:
            await self.uow.user_establishment_repo.update_status_for_ids(
                user_id, establishment_ids, UserEstablishmentStatus.REJECTED
            )
        await self.uow.user_repo.update_status(user_id, UserStatus.INACTIVE)
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
            role=role,
            status=status,
            limit=page_size,
            offset=offset,
            search=search,
        )

        return await self._build_paginated_users_result(users, total, page, page_size)

    async def invite_user(self, data: InviteAdminRequest, role: UserRole) -> UUID:
        """Create a new admin user and send a password setup link by email.

        Returns:
            The id of the newly created user.

        Raises:
            UserAlreadyExistsError: If the email already belongs to a user,
                regardless of that user's status.
                Use resend_invite to re-send a pending invitation.
            EmailDeliveryError: If the invitation email could not be delivered.
        """
        email = data.email.strip().lower()
        if await self.uow.user_repo.exists_by_email(email):
            raise UserAlreadyExistsError(email)

        user = await self.uow.user_repo.create(
            email=email,
            name="",
            last_name="",
            role=role,
            status=UserStatus.PENDING_VALIDATION,
        )
        placeholder_password = secrets.token_urlsafe(32)
        await self.uow.password_repo.create(
            user.id, hash_password(placeholder_password)
        )
        await self.uow.commit()

        await self._issue_and_send_invite(user)
        return user.id

    async def resend_invite(self, user_id: UUID) -> None:
        """Re-send the invitation email for a still-pending invited user.

        Raises:
            UserNotFoundError: If no user with the given id exists.
            BadRequestError: If the user already completed onboarding
                (status is not PENDING_VALIDATION), or is not a backoffice
                user (e.g. a self-registered field worker, who is also
                PENDING_VALIDATION but was never invited).
            EmailDeliveryError: If the invitation email could not be delivered.
        """
        user = await self.uow.user_repo.get_by_id(user_id)
        if user is None:
            raise UserNotFoundError(str(user_id))

        if user.status != UserStatus.PENDING_VALIDATION:
            raise BadRequestError(
                "User is not pending",
                "Only users with a pending invitation can be re-invited.",
            )

        await self._issue_and_send_invite(user)

    async def get_user_info(self, user_id: UUID) -> UserWithEstablishmentsDomain:
        """Return a user with fully hydrated establishment objects.

        Raises:
            UserNotFoundError: If no user with user_id exists.
        """
        user = await self.uow.user_repo.get_by_id(user_id)
        if user is None:
            raise UserNotFoundError(str(user_id))
        establishments_per_user = await self._get_establishments_per_user([user.id])
        return UserWithEstablishmentsDomain.from_db(
            user, establishments_per_user.get(user.id, [])
        )
