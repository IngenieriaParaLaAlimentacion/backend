"""Per-establishment access checks shared by the services that need them.

The token carries a role but no establishment scope, so a field worker's right
to act on a given establishment is resolved at request time against their
approved relations. Every service that writes or reads establishment-scoped
data goes through here rather than re-deriving the rule.
"""

from uuid import UUID

from app.core.interfaces.unit_of_work import IUnitOfWork
from app.domain import UserActor, UserRole
from app.domain.establishment import UserEstablishmentStatus
from app.exceptions.domain_exceptions import EstablishmentAccessDeniedError


async def check_establishment_access(
    uow: IUnitOfWork, actor: UserActor, establishment_id: UUID
) -> None:
    """Allow the actor to act on this establishment, or raise.

    Only field workers are scoped: an admin or analyst works across every
    establishment by definition of their role.

    Raises:
        EstablishmentAccessDeniedError: the actor is a field worker with no
            approved relation to this establishment.
    """
    if actor.role != UserRole.FIELD_WORKER:
        return
    relation = await uow.user_establishment_repo.get_relation(
        actor.user_id, establishment_id
    )
    if relation is None or relation.status != UserEstablishmentStatus.APPROVED:
        raise EstablishmentAccessDeniedError()
