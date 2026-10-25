import secrets
from typing import Any
from uuid import UUID

from app.core.interfaces.unit_of_work import IUnitOfWork
from app.core.security import hash_password
from app.domain.establishment import EstablishmentDomain, UserEstablishmentStatus
from app.domain.pagination import PaginatedResult
from app.domain.subject import SubjectDomain
from app.domain.subject_event import SubjectEventRecord
from app.domain.user import (
    BACKOFFICE_ROLES,
    REVIEWED_ACCESS_ROLES,
    UserActor,
    UserRole,
    UserStatus,
    UserWithEstablishmentsDomain,
)
from app.exceptions.domain_exceptions import (
    FieldWorkerNotPendingError,
    InvalidUserRoleError,
    InvitePendingError,
    RoleNotAllowedError,
    SubjectNotFoundError,
    UserAlreadyExistsError,
    UserEstablishmentNotApprovedError,
    UserEstablishmentNotFoundError,
    UserNotActiveError,
    UserNotFieldWorkerError,
    UserNotFoundError,
    UserNotPendingError,
)
from app.models.auth.user import User
from app.schemas.auth.admin_schema import InviteAdminRequest
from app.services.auth.auth_service import AuthService
from app.services.email_service import (
    build_invite_deeplink,
    send_access_granted_email,
    send_invite_email,
    send_role_changed_email,
)

# Actor role -> roles of the users it may change. The schema already limits the
# destination role to field_worker, analyst or admin.
_ROLE_CHANGE_SOURCES: dict[UserRole, frozenset[UserRole]] = {
    UserRole.ADMIN: frozenset({UserRole.FIELD_WORKER, UserRole.ANALYST}),
    UserRole.SUPERADMIN: frozenset(
        {UserRole.FIELD_WORKER, UserRole.ANALYST, UserRole.ADMIN}
    ),
}


class AdminService:
    """Service layer for admin-related business logic."""

    def __init__(self, uow: IUnitOfWork, auth_service: AuthService) -> None:
        self.uow = uow
        self.auth_service = auth_service

    async def _get_user(self, user_id: UUID) -> Any:
        """Return the user, raising if they do not exist."""
        user = await self.uow.user_repo.get_by_id(user_id)
        if user is None:
            raise UserNotFoundError(str(user_id))
        return user

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
        self,
        user_ids: list[UUID],
        status: UserEstablishmentStatus,
    ) -> dict[UUID, list[EstablishmentDomain]]:
        """Return the full establishment details for each user."""
        estab_ids_by_user: dict[
            UUID, list[UUID]
        ] = await self.uow.user_establishment_repo.get_by_user_ids(user_ids, status)

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

    async def _build_paginated_users_result(
        self,
        users: list[User],
        total: int,
        page: int,
        page_size: int,
        status: UserEstablishmentStatus,
    ) -> PaginatedResult[UserWithEstablishmentsDomain]:
        """Hydrate establishments for `users` and wrap them in a PaginatedResult.

        ``status`` narrows the hydrated establishments to relations in that
        status, and is required for the reason given on
        _get_establishments_per_user.
        """
        if not users:
            return PaginatedResult(
                items=[],
                total=total,
                page=page,
                page_size=page_size,
                total_pages=0,
            )

        establishments_per_user = await self._get_establishments_per_user(
            [user.id for user in users], status
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

    async def _get_field_worker_relations(self, user_id: UUID) -> tuple[Any, list]:
        """Return (user, relations) for a field worker, raising if the user does
        not exist."""
        user = await self._get_user(user_id)
        relations = await self.uow.user_establishment_repo.get_by_user_id(user_id)
        return user, relations

    @staticmethod
    def _match_relations(
        user_id: UUID, establishment_ids: list[UUID], relations: list[Any]
    ) -> dict[UUID, Any]:
        """Map establishment_ids to their relation, raising if any id has no
        relation with the user."""
        relations_by_estab_id = {rel.establishment_id: rel for rel in relations}

        invalid_ids = set(establishment_ids) - relations_by_estab_id.keys()
        if invalid_ids:
            raise UserEstablishmentNotFoundError(
                str(next(iter(invalid_ids))), str(user_id)
            )
        return relations_by_estab_id

    async def _validate_access_request(
        self, user_id: UUID, establishment_ids: list[UUID]
    ) -> dict[UUID, Any]:
        """Validate that all establishment IDs belong to the field worker and
        return their relations keyed by establishment id."""
        _, relations = await self._get_field_worker_relations(user_id)
        return self._match_relations(user_id, establishment_ids, relations)

    @staticmethod
    def _require_field_worker(user: Any, error_detail: str) -> None:
        """Raise UserNotFieldWorkerError unless the user is a field worker."""
        if user.role != UserRole.FIELD_WORKER:
            raise UserNotFieldWorkerError(error_detail)

    async def _get_field_worker(self, user_id: UUID, error_detail: str) -> Any:
        """Return the user, raising if they do not exist or are not a field worker."""
        user = await self._get_user(user_id)
        self._require_field_worker(user, error_detail)
        return user

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
            InvalidUserRoleError: If the user's role is not a backoffice role.
            EmailDeliveryError: If the invitation email could not be delivered.
        """
        if user.role not in BACKOFFICE_ROLES:
            raise InvalidUserRoleError()

        created_token, plain_token = await self.auth_service.create_recovery_token(
            user.id
        )
        await self.uow.commit()
        await send_invite_email(
            user.email,
            build_invite_deeplink(plain_token, user.role),
            created_token.expires_at,
            user.role,
            user.name or None,
        )

    async def get_users_paginated(
        self,
        page: int,
        page_size: int,
        role: UserRole | None = None,
        status: UserStatus | None = None,
        search: str | None = None,
    ) -> PaginatedResult[UserWithEstablishmentsDomain]:
        """Return a paginated list of users with their approved establishments.

        Only approved relations are hydrated: a pending request is not access,
        and is surfaced by get_pending_establishment_requests instead.

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

        return await self._build_paginated_users_result(
            users, total, page, page_size, UserEstablishmentStatus.APPROVED
        )

    async def get_pending_establishment_requests(
        self,
        page: int,
        page_size: int,
        search: str | None = None,
        establishment_id: UUID | None = None,
    ) -> tuple[PaginatedResult[UserWithEstablishmentsDomain], int]:
        """Return active field workers and analysts awaiting establishment access.

        Each user carries only their pending establishments. ``search`` matches
        case-insensitively against email, name, and last_name; whitespace-only
        values are treated as no filter. ``establishment_id`` keeps only the
        users pending on that establishment.

        The second tuple element is the total number of pending establishment
        relations across every matching user, not just this page.
        """
        offset = (page - 1) * page_size
        search = search.strip() or None if search else None

        users, total = await self.uow.user_repo.get_pending_establishments_page(
            limit=page_size,
            offset=offset,
            search=search,
            establishment_id=establishment_id,
        )
        result = await self._build_paginated_users_result(
            users, total, page, page_size, UserEstablishmentStatus.PENDING
        )
        total_pending = await self.uow.user_repo.count_pending_establishments(
            search=search, establishment_id=establishment_id
        )
        return result, total_pending

    async def get_user_info(self, user_id: UUID) -> UserWithEstablishmentsDomain:
        """Return a user with their approved establishments fully hydrated.

        Pending and rejected relations are excluded — they are requests, not
        access.

        Raises:
            UserNotFoundError: If no user with user_id exists.
        """
        user = await self._get_user(user_id)
        establishments_per_user = await self._get_establishments_per_user(
            [user.id], UserEstablishmentStatus.APPROVED
        )
        return UserWithEstablishmentsDomain.from_db(
            user, establishments_per_user.get(user.id, [])
        )

    async def change_user_role(
        self, actor: UserActor, user_id: UUID, new_role: UserRole
    ) -> UserWithEstablishmentsDomain:
        """Change a user's role, revoke their refresh tokens and notify them by
        email. Requesting the role the user already has is a no-op.

        Returns:
            The user with their approved establishments, as get_user_info.

        Raises:
            UserNotFoundError: If no user with user_id exists.
            RoleNotAllowedError: If the actor targets themselves or a user whose
                role they are not allowed to change.
            UserNotActiveError: If the user's account is not active.
        """
        user = await self._get_user(user_id)
        if actor.user_id == user_id or user.role not in _ROLE_CHANGE_SOURCES.get(
            actor.role, frozenset()
        ):
            raise RoleNotAllowedError("You are not allowed to change this user's role.")
        # The invite link depends on the role, so pending users keep theirs.
        if user.status != UserStatus.ACTIVE:
            raise UserNotActiveError("Only active users can have their role changed.")
        if user.role == new_role:
            return await self.get_user_info(user_id)

        old_role = user.role
        await self.uow.user_repo.update_role(user_id, new_role)
        # Refresh reissues access tokens with the stored role, so old sessions
        # must go for the new role to take effect.
        await self.uow.token_repo.revoke_all_by_user_id(user_id)
        await self.uow.commit()

        await send_role_changed_email(user.email, old_role, new_role, user.name)
        return await self.get_user_info(user_id)

    async def approve_establishments(
        self, user_id: UUID, establishment_ids: list[UUID]
    ) -> None:
        """Approve access to the given establishments.

        Raises:
            UserNotFoundError: If the user does not exist.
            UserNotActiveError: If the user's account is not active yet.
        """
        user = await self._get_user(user_id)
        if user.status != UserStatus.ACTIVE:
            raise UserNotActiveError(
                "Only active users can be granted access to establishments."
            )

        await self._set_user_establishment_relation_status(
            user_id, establishment_ids, UserEstablishmentStatus.APPROVED
        )
        await self.uow.commit()

        establishments = await self.uow.establishment_repo.find_by_ids(
            establishment_ids
        )
        await send_access_granted_email(
            user.email,
            [e.name for e in establishments],
            user.name,
        )

    async def reject_establishments(
        self, user_id: UUID, establishment_ids: list[UUID]
    ) -> None:
        """Reject access to the given establishments. Does not change user status."""
        await self._set_user_establishment_relation_status(
            user_id, establishment_ids, UserEstablishmentStatus.REJECTED
        )
        await self.uow.commit()

    async def revoke_establishments(
        self, user_id: UUID, establishment_ids: list[UUID]
    ) -> None:
        """Revoke previously approved access to the given establishments.
        Does not change the user's account status.

        Raises:
            UserNotFoundError: If the user does not exist.
            UserNotFieldWorkerError: If the user is neither a field worker nor
                an analyst.
            UserEstablishmentNotFoundError: If an establishment has no relation
                with this user.
            UserEstablishmentNotApprovedError: If an establishment has a
                relation with this user, but it isn't currently approved.
        """
        user, relations = await self._get_field_worker_relations(user_id)
        if user.role not in REVIEWED_ACCESS_ROLES:
            raise UserNotFieldWorkerError(
                "Only field workers and analysts can have establishment access revoked."
            )

        relations_by_estab_id = self._match_relations(
            user_id, establishment_ids, relations
        )
        not_approved_ids = [
            estab_id
            for estab_id in establishment_ids
            if relations_by_estab_id[estab_id].status
            != UserEstablishmentStatus.APPROVED
        ]
        if not_approved_ids:
            raise UserEstablishmentNotApprovedError(
                str(not_approved_ids[0]),
                str(user_id),
                relations_by_estab_id[not_approved_ids[0]].status.value,
            )

        await self.uow.user_establishment_repo.update_status_for_ids(
            user_id, establishment_ids, UserEstablishmentStatus.REVOKED
        )
        await self.uow.commit()

    async def approve_field_worker(
        self, user_id: UUID, establishment_ids: list[UUID]
    ) -> None:
        """Accept a field worker's request and approve the selected establishments.

        ``establishment_ids`` may be empty: the account is activated and every
        establishment request stays pending.

        Raises:
            UserNotFoundError: If the user does not exist.
            UserNotFieldWorkerError: If the user is not a field worker.
            FieldWorkerNotPendingError: If the field worker is not in
                pending status.
            UserEstablishmentNotFoundError: If an establishment was not
                requested by this field worker.
        """
        user = await self._get_field_worker(
            user_id, "Only field workers go through establishment approval."
        )
        if user.status != UserStatus.PENDING_VALIDATION:
            raise FieldWorkerNotPendingError(
                "Only field workers with pending status can be approved through "
                "this endpoint."
            )

        await self.uow.user_repo.update_status(user_id, UserStatus.ACTIVE)
        if establishment_ids:
            await self._set_user_establishment_relation_status(
                user_id, establishment_ids, UserEstablishmentStatus.APPROVED
            )
        await self.uow.commit()

        if not establishment_ids:
            return

        establishments = await self.uow.establishment_repo.find_by_ids(
            establishment_ids
        )
        await send_access_granted_email(
            user.email,
            [e.name for e in establishments],
            user.name,
        )

    async def reject_field_worker(self, user_id: UUID) -> None:
        """Reject all establishment access for the given field worker and
        mark them inactive.

        Raises:
            UserNotFoundError: If the user does not exist.
            FieldWorkerNotPendingError: If the field worker is not in pending
                status.
        """
        user, relations = await self._get_field_worker_relations(user_id)
        if user.status != UserStatus.PENDING_VALIDATION:
            raise FieldWorkerNotPendingError(
                "Only field workers with pending status can be rejected through "
                "this endpoint."
            )
        establishment_ids = [rel.establishment_id for rel in relations]

        if establishment_ids:
            await self.uow.user_establishment_repo.update_status_for_ids(
                user_id, establishment_ids, UserEstablishmentStatus.REJECTED
            )
        await self.uow.user_repo.update_status(user_id, UserStatus.INACTIVE)
        await self.uow.commit()

    async def invite_user(self, data: InviteAdminRequest, role: UserRole) -> UUID:
        """Create a new admin user and send a password setup link by email.

        Returns:
            The id of the newly created user.

        Raises:
            InvitePendingError: If the email already has an unaccepted
                backoffice invitation. Carries the ``user_id`` extension so the
                caller can hand it to resend_invite.
            UserAlreadyExistsError: If the email belongs to any other user.
            EmailDeliveryError: If the invitation email could not be delivered.
        """
        email = data.email.strip().lower()
        existing = await self.uow.user_repo.get_by_email(email)
        if existing is not None:
            if (
                existing.status == UserStatus.PENDING_VALIDATION
                and existing.role in BACKOFFICE_ROLES
            ):
                raise InvitePendingError(str(existing.id))
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
            UserNotPendingError: If the user already completed onboarding
                (status is not PENDING_VALIDATION).
            InvalidUserRoleError: If the user is not a backoffice user (e.g. a
                self-registered field worker, who is also PENDING_VALIDATION
                but was never invited).
            EmailDeliveryError: If the invitation email could not be delivered.
        """
        user = await self._get_user(user_id)
        if user.status != UserStatus.PENDING_VALIDATION:
            raise UserNotPendingError(
                "Only users with a pending invitation can be re-invited."
            )

        await self._issue_and_send_invite(user)

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
