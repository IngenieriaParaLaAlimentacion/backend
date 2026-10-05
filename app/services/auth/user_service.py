from dataclasses import fields
from uuid import UUID

from app.core.interfaces.unit_of_work import IUnitOfWork
from app.domain.establishment import (
    EstablishmentDomain,
    EstablishmentWithStatusDomain,
    UserEstablishmentStatus,
)
from app.domain.user import ProfileDomain, UserActor, UserRole
from app.exceptions.domain_exceptions import (
    EmptyUpdateRequestError,
    RoleNotAllowedError,
    UserEstablishmentNotFoundError,
    UserEstablishmentNotWithdrawableError,
    UserNotFoundError,
)
from app.models.auth.user import User
from app.schemas.auth.user_schema import ProfileUpdateRequest

_ESTABLISHMENT_FIELDS = tuple(f.name for f in fields(EstablishmentDomain))
# Roles that subscribe directly instead of requesting access for review.
_SUBSCRIBER_ROLES = {UserRole.ADMIN, UserRole.SUPERADMIN}


def _establishment_snapshot(establishment) -> dict:
    """Snapshot an establishment's scalar fields into a plain dict.

    Taken before commit so a status-annotated domain can be built afterwards
    without triggering async ORM attribute expiry.
    """
    return {name: getattr(establishment, name) for name in _ESTABLISHMENT_FIELDS}


class UserService:
    """Service layer for current-user (profile) reads and edits."""

    def __init__(self, uow: IUnitOfWork) -> None:
        self.uow = uow

    async def _get_user_or_raise(self, actor: UserActor) -> User:
        """Load the authenticated user, raising if it no longer exists.

        Raises:
            UserNotFoundError: If the token's user no longer exists.
        """
        user = await self.uow.user_repo.get_by_id(actor.user_id)
        if user is None:
            raise UserNotFoundError(str(actor.user_id))
        return user

    async def _build_profile(self, user: User) -> ProfileDomain:
        """Assemble a ProfileDomain from a loaded user."""
        establishments = await self._get_establishments_with_status(user.id)
        return ProfileDomain(
            id=user.id,
            email=user.email,
            name=user.name,
            last_name=user.last_name,
            role=user.role,
            status=user.status,
            is_email_verified=user.is_email_verified,
            establishments=establishments,
            locality=user.locality,
            description=user.description,
            contact_phone=user.contact_phone,
        )

    async def _get_status_by_establishment(
        self, user_id: UUID
    ) -> dict[UUID, UserEstablishmentStatus]:
        """Return the caller's establishment ids mapped to their relation status."""
        relations = await self.uow.user_establishment_repo.get_by_user_id(user_id)
        return {rel.establishment_id: rel.status for rel in relations}

    @staticmethod
    def _to_establishment_status_domains(
        ids: list[UUID],
        info: dict[UUID, dict],
        result_status: dict[UUID, UserEstablishmentStatus],
    ) -> list[EstablishmentWithStatusDomain]:
        """Zip establishment snapshots with their resulting status, in id order."""
        return [
            EstablishmentWithStatusDomain(
                **info[estab_id], status=result_status[estab_id]
            )
            for estab_id in ids
        ]

    async def _get_establishments_with_status(
        self, user_id: UUID
    ) -> list[EstablishmentWithStatusDomain]:
        status_by_estab = await self._get_status_by_establishment(user_id)
        if not status_by_estab:
            return []

        establishments = await self.uow.establishment_repo.find_by_ids(
            list(status_by_estab.keys())
        )
        by_id = {establishment.id: establishment for establishment in establishments}

        result: list[EstablishmentWithStatusDomain] = []
        for estab_id, status in status_by_estab.items():
            establishment = by_id.get(estab_id)
            if establishment is None:
                continue
            result.append(
                EstablishmentWithStatusDomain(
                    **_establishment_snapshot(establishment),
                    status=status,
                )
            )
        return result

    @staticmethod
    def _classify_for_request(
        unique_ids: list[UUID],
        status_by_estab: dict[UUID, UserEstablishmentStatus],
    ) -> tuple[list[UUID], list[UUID], dict[UUID, UserEstablishmentStatus]]:
        """Sort ids into what a request/re-request must do to each one.

        Returns (to_repend, to_insert, result_status): approved/pending relations
        are left as-is; rejected/revoked/withdrawn ones are re-pended to pending;
        ids with no relation yet are inserted as pending. ``result_status`` holds
        the status every id will end up with, for building the response.
        """
        to_repend: list[UUID] = []
        to_insert: list[UUID] = []
        result_status: dict[UUID, UserEstablishmentStatus] = {}
        for estab_id in unique_ids:
            current = status_by_estab.get(estab_id)
            if current in (
                UserEstablishmentStatus.APPROVED,
                UserEstablishmentStatus.PENDING,
            ):
                result_status[estab_id] = current
            elif current in (
                UserEstablishmentStatus.REJECTED,
                UserEstablishmentStatus.REVOKED,
                UserEstablishmentStatus.WITHDRAWN,
            ):
                to_repend.append(estab_id)
                result_status[estab_id] = UserEstablishmentStatus.PENDING
            else:
                to_insert.append(estab_id)
                result_status[estab_id] = UserEstablishmentStatus.PENDING
        return to_repend, to_insert, result_status

    async def get_profile(self, actor: UserActor) -> ProfileDomain:
        """Return the authenticated user's profile.

        Raises:
            UserNotFoundError: If the token's user no longer exists.
        """
        user = await self._get_user_or_raise(actor)
        return await self._build_profile(user)

    async def update_profile(
        self, actor: UserActor, data: ProfileUpdateRequest
    ) -> ProfileDomain:
        """Update the caller's editable profile fields and return the new profile.

        Raises:
            UserNotFoundError: If the token's user no longer exists.
            EmptyUpdateRequestError: If no editable field was provided.
        """
        user = await self._get_user_or_raise(actor)

        values = data.model_dump(exclude_unset=True, exclude_none=True)
        if not values:
            raise EmptyUpdateRequestError()

        # Capture scalars before the write/commit to avoid async attribute expiry.
        email, role, status = user.email, user.role, user.status
        name = values.get("name", user.name)
        last_name = values.get("last_name", user.last_name)
        locality = values.get("locality", user.locality)
        description = values.get("description", user.description)
        contact_phone = values.get("contact_phone", user.contact_phone)

        await self.uow.user_repo.update_profile(user.id, values)
        await self.uow.commit()

        establishments = await self._get_establishments_with_status(user.id)

        return ProfileDomain(
            id=user.id,
            email=email,
            name=name,
            last_name=last_name,
            role=role,
            status=status,
            is_email_verified=user.is_email_verified,
            establishments=establishments,
            locality=locality,
            description=description,
            contact_phone=contact_phone,
        )

    async def get_own_establishments(
        self, actor: UserActor
    ) -> list[EstablishmentWithStatusDomain]:
        """Return the caller's establishment relations, each with its status."""
        return await self._get_establishments_with_status(actor.user_id)

    async def request_establishment_access(
        self, actor: UserActor, establishment_ids: list[UUID]
    ) -> list[EstablishmentWithStatusDomain]:
        """Request (or re-request) access to establishments. Idempotent per item:
        approved/pending stay as-is, rejected/revoked/withdrawn/new become
        pending.

        Raises:
            RoleNotAllowedError: If the caller is an admin, who subscribes instead.
            EstablishmentNotFoundError: If any establishment id does not exist.
        """
        if actor.role in _SUBSCRIBER_ROLES:
            raise RoleNotAllowedError(
                "Admins subscribe to establishments instead of requesting access."
            )
        user_id = actor.user_id
        unique_ids = list(dict.fromkeys(establishment_ids))

        establishments = await self.uow.establishment_repo.get_all_by_ids(unique_ids)
        info = {e.id: _establishment_snapshot(e) for e in establishments}

        status_by_estab = await self._get_status_by_establishment(user_id)
        to_repend, to_insert, result_status = self._classify_for_request(
            unique_ids, status_by_estab
        )

        if to_repend:
            await self.uow.user_establishment_repo.update_status_for_ids(
                user_id, to_repend, UserEstablishmentStatus.PENDING
            )
        for estab_id in to_insert:
            await self.uow.user_establishment_repo.preset_relation(user_id, estab_id)
        await self.uow.commit()

        return self._to_establishment_status_domains(unique_ids, info, result_status)

    async def withdraw_establishment_access(
        self, actor: UserActor, establishment_ids: list[UUID]
    ) -> list[EstablishmentWithStatusDomain]:
        """Withdraw the caller's own access to one or more establishments.

        Only relations currently approved or pending can be withdrawn.
        A withdrawn establishment can be re-requested through
        request_establishment_access exactly like a rejected or revoked one.

        Raises:
            RoleNotAllowedError: If the caller is an admin, who unsubscribes
                instead.
            UserEstablishmentNotFoundError: If an establishment id has no
                relation with the caller.
            UserEstablishmentNotWithdrawableError: If a relation exists but is
                not currently approved or pending.
        """
        if actor.role in _SUBSCRIBER_ROLES:
            raise RoleNotAllowedError(
                "Admins unsubscribe from establishments instead of withdrawing."
            )
        user_id = actor.user_id
        unique_ids = list(dict.fromkeys(establishment_ids))

        status_by_estab = await self._get_status_by_establishment(user_id)

        to_withdraw: list[UUID] = []
        for estab_id in unique_ids:
            current = status_by_estab.get(estab_id)
            if current is None:
                raise UserEstablishmentNotFoundError(str(estab_id), str(user_id))
            if current not in (
                UserEstablishmentStatus.APPROVED,
                UserEstablishmentStatus.PENDING,
            ):
                raise UserEstablishmentNotWithdrawableError(
                    str(estab_id), str(user_id), current.value
                )
            to_withdraw.append(estab_id)

        await self.uow.user_establishment_repo.update_status_for_ids(
            user_id, to_withdraw, UserEstablishmentStatus.WITHDRAWN
        )
        await self.uow.commit()

        establishments = await self.uow.establishment_repo.find_by_ids(unique_ids)
        info = {e.id: _establishment_snapshot(e) for e in establishments}
        result_status = dict.fromkeys(unique_ids, UserEstablishmentStatus.WITHDRAWN)

        return self._to_establishment_status_domains(unique_ids, info, result_status)

    async def subscribe_to_establishments(
        self, actor: UserActor, establishment_ids: list[UUID]
    ) -> list[EstablishmentWithStatusDomain]:
        """Grant the caller approved access to establishments, with no review.

        Idempotent per item: already-approved relations stay as-is, relations in
        any other status (e.g. from before a promotion to admin) are flipped to
        approved, and missing ones are created as approved.

        Raises:
            EstablishmentNotFoundError: If any establishment id does not exist.
        """
        unique_ids = list(dict.fromkeys(establishment_ids))

        establishments = await self.uow.establishment_repo.get_all_by_ids(unique_ids)
        info = {e.id: _establishment_snapshot(e) for e in establishments}

        await self.uow.user_establishment_repo.approve_relations(
            actor.user_id, unique_ids
        )
        await self.uow.commit()

        result_status = dict.fromkeys(unique_ids, UserEstablishmentStatus.APPROVED)
        return self._to_establishment_status_domains(unique_ids, info, result_status)

    async def unsubscribe_from_establishments(
        self, actor: UserActor, establishment_ids: list[UUID]
    ) -> None:
        """Delete the caller's relations to establishments.

        Idempotent per item: ids the caller has no relation with are skipped.
        """
        await self.uow.user_establishment_repo.delete_relations(
            actor.user_id, list(dict.fromkeys(establishment_ids))
        )
        await self.uow.commit()
