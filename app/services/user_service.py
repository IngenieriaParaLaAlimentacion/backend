from uuid import UUID

from app.core.interfaces.unit_of_work import IUnitOfWork
from app.domain.establishment import EstablishmentWithStatusDomain
from app.domain.user import ProfileDomain, UserActor, UserRole
from app.exceptions.domain_exceptions import UserNotFoundError


class UserService:
    """Service layer for current-user (profile) reads."""

    def __init__(self, uow: IUnitOfWork) -> None:
        self.uow = uow

    async def get_profile(self, actor: UserActor) -> ProfileDomain:
        """Return the authenticated user's profile.

        Establishments are included only for establishment managers; for other
        roles the field is None (no establishments section).

        Raises:
            UserNotFoundError: If the token's user no longer exists.
        """
        user_id = UUID(str(actor.user_id))
        user = await self.uow.user_repo.get_by_id(user_id)
        if user is None:
            raise UserNotFoundError(str(user_id))

        establishments = None
        if user.role == UserRole.ESTABLISHMENT_MANAGER:
            establishments = await self._get_establishments_with_status(user_id)

        return ProfileDomain(
            id=user.id,
            email=user.email,
            name=user.name,
            last_name=user.last_name,
            role=user.role,
            status=user.status,
            establishments=establishments,
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
                    id=establishment.id,
                    name=establishment.name,
                    address=establishment.address,
                    status=relation.status,
                )
            )
        return result
