"""Access checks shared by the services and dependencies that need them.

The token carries a role but no establishment scope, so a user's right to act
on a given establishment is resolved at request time against their approved
relations. Every service that writes or reads establishment-scoped data goes
through here rather than re-deriving the rule.

The token also cannot tell whether the user was blocked after it was issued, so
every authenticated request checks the user's status here as well.
"""

from uuid import UUID

from app.core.interfaces.unit_of_work import IUnitOfWork
from app.domain import UserActor, UserRole, UserStatus
from app.domain.establishment import UserEstablishmentStatus
from app.exceptions.domain_exceptions import (
    EstablishmentAccessDeniedError,
    UserBlockedError,
)


async def _has_approved_relation(
    uow: IUnitOfWork, user_id: UUID, establishment_id: UUID
) -> bool:
    """Return whether the user has approved access to the establishment."""
    relation = await uow.user_establishment_repo.get_relation(user_id, establishment_id)
    return relation is not None and relation.status == UserEstablishmentStatus.APPROVED


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
    if not await _has_approved_relation(uow, actor.user_id, establishment_id):
        raise EstablishmentAccessDeniedError()


async def check_field_work_access(
    uow: IUnitOfWork, actor: UserActor, establishment_id: UUID | None
) -> None:
    """Allow the actor to do field work that only field workers get by role,
    or raise.

    Only analysts are scoped: they need approved access to ``establishment_id``,
    or to any establishment when the work names none. Every other role is
    allowed by its role alone.

    Raises:
        EstablishmentAccessDeniedError: the actor is an analyst without the
            required approved relation.
    """
    if actor.role != UserRole.ANALYST:
        return
    if establishment_id is not None:
        allowed = await _has_approved_relation(uow, actor.user_id, establishment_id)
    else:
        allowed = bool(
            await uow.user_establishment_repo.get_approved_establishment_ids(
                actor.user_id
            )
        )
    if not allowed:
        raise EstablishmentAccessDeniedError()


async def check_user_not_blocked(uow: IUnitOfWork, user_id: UUID) -> None:
    """Validate that the user is not blocked.

    Raises:
        UserBlockedError: the actor is blocked.
    """
    status = await uow.user_repo.get_status(user_id)
    if status == UserStatus.BLOCKED:
        raise UserBlockedError()
