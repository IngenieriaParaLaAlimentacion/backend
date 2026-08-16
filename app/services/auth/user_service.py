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
    UserNotFoundError,
)
from app.models.auth.user import User
from app.schemas.auth.user_schema import ProfileUpdateRequest

_ESTABLISHMENT_FIELDS = tuple(f.name for f in fields(EstablishmentDomain))


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
        """Assemble a ProfileDomain from a loaded user.

        Establishments are included only for field workers.
        """
        establishments = None
        if user.role == UserRole.FIELD_WORKER:
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

    async def _get_establishments_with_status(
        self, user_id: UUID
    ) -> list[EstablishmentWithStatusDomain]:
        relations = await self.uow.user_establishment_repo.get_by_user_id(user_id)
        if not relations:
            return []

        establishments = await self.uow.establishment_repo.find_by_ids(
            [relation.establishment_id for relation in relations]
        )
        by_id = {establishment.id: establishment for establishment in establishments}

        result: list[EstablishmentWithStatusDomain] = []
        for relation in relations:
            establishment = by_id.get(relation.establishment_id)
            if establishment is None:
                continue
            result.append(
                EstablishmentWithStatusDomain(
                    **_establishment_snapshot(establishment),
                    status=relation.status,
                )
            )
        return result

    async def get_profile(self, actor: UserActor) -> ProfileDomain:
        """Return the authenticated user's profile.

        Establishments are included only for field workers; for other
        roles the field is None (no establishments section).

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

        establishments = None
        if role == UserRole.FIELD_WORKER:
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
        approved/pending stay as-is, rejected/new become pending.

        Raises:
            EstablishmentNotFoundError: If any establishment id does not exist.
        """
        user_id = actor.user_id
        unique_ids = list(dict.fromkeys(establishment_ids))

        establishments = await self.uow.establishment_repo.get_all_by_ids(unique_ids)
        info = {e.id: _establishment_snapshot(e) for e in establishments}

        relations = await self.uow.user_establishment_repo.get_by_user_id(user_id)
        status_by_estab = {rel.establishment_id: rel.status for rel in relations}

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
            elif current == UserEstablishmentStatus.REJECTED:
                to_repend.append(estab_id)
                result_status[estab_id] = UserEstablishmentStatus.PENDING
            else:
                to_insert.append(estab_id)
                result_status[estab_id] = UserEstablishmentStatus.PENDING

        if to_repend:
            await self.uow.user_establishment_repo.update_status_for_ids(
                user_id, to_repend, UserEstablishmentStatus.PENDING
            )
        for estab_id in to_insert:
            await self.uow.user_establishment_repo.preset_relation(user_id, estab_id)
        await self.uow.commit()

        return [
            EstablishmentWithStatusDomain(
                **info[estab_id], status=result_status[estab_id]
            )
            for estab_id in unique_ids
        ]
