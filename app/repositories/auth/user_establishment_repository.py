from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.establishment import UserEstablishmentStatus
from app.domain.user import UserRole, UserStatus
from app.models.auth.user import User
from app.models.auth.user_establishment import UserEstablishment


class UserEstablishmentRepository:
    """Persistence operations for UserEstablishment association records."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def preset_relation(
        self, user_id: UUID, establishment_id: UUID
    ) -> UserEstablishment:
        """Stage a pending user-establishment relation for a
        field worker registration."""
        status = UserEstablishmentStatus.PENDING
        user_establishment = UserEstablishment(
            user_id=user_id, establishment_id=establishment_id, status=status
        )
        self.db.add(user_establishment)
        return user_establishment

    async def create_or_approve_relation(
        self, user_id: UUID, establishment_id: UUID
    ) -> UserEstablishment:
        """Grant the user approved access to the establishment.

        Creates the relation as approved if none exists yet; if one already
        exists (e.g. a pending relation from registration), flips it to
        approved instead of creating a duplicate row.
        """
        relation = await self.get_relation(user_id, establishment_id)
        if relation is None:
            relation = UserEstablishment(
                user_id=user_id,
                establishment_id=establishment_id,
                status=UserEstablishmentStatus.APPROVED,
            )
            self.db.add(relation)
        else:
            relation.status = UserEstablishmentStatus.APPROVED
        return relation

    async def get_by_user_ids(
        self,
        user_ids: list[UUID],
        status: UserEstablishmentStatus | None = None,
    ) -> dict[UUID, list[UUID]]:
        """Return a list of establishment ids for each of the given users.

        ``status`` optionally restricts the result to relations in that status.
        """
        query = select(
            UserEstablishment.user_id, UserEstablishment.establishment_id
        ).where(UserEstablishment.user_id.in_(user_ids))
        if status is not None:
            query = query.where(UserEstablishment.status == status)

        result = await self.db.execute(query)
        mapping: dict[UUID, list[UUID]] = {user_id: [] for user_id in user_ids}
        for user_id, estab_id in result.all():
            mapping[user_id].append(estab_id)
        return mapping

    async def get_by_user_id(self, user_id: UUID) -> list[UserEstablishment]:
        """Return all UserEstablishment records for a given user."""
        result = await self.db.execute(
            select(UserEstablishment).where(UserEstablishment.user_id == user_id)
        )
        return list(result.scalars().all())

    async def get_approved_establishment_ids(self, user_id: UUID) -> set[UUID]:
        """Return the ids of establishments the user has approved access to."""
        result = await self.db.execute(
            select(UserEstablishment.establishment_id).where(
                UserEstablishment.user_id == user_id,
                UserEstablishment.status == UserEstablishmentStatus.APPROVED,
            )
        )
        return set(result.scalars().all())

    async def count_by_status(self, status: UserEstablishmentStatus) -> int:
        """Return how many relations in the given status belong to active
        field workers."""
        result = await self.db.execute(
            select(func.count())
            .select_from(UserEstablishment)
            .join(User, User.id == UserEstablishment.user_id)
            .where(
                UserEstablishment.status == status,
                User.role == UserRole.FIELD_WORKER,
                User.status == UserStatus.ACTIVE,
            )
        )
        return result.scalar_one()

    async def get_relation(
        self, user_id: UUID, establishment_id: UUID
    ) -> UserEstablishment | None:
        """Return the user-establishment relation regardless of status, or None."""
        result = await self.db.execute(
            select(UserEstablishment).where(
                UserEstablishment.user_id == user_id,
                UserEstablishment.establishment_id == establishment_id,
            )
        )
        return result.scalar_one_or_none()

    async def update_status_for_ids(
        self,
        user_id: UUID,
        establishment_ids: list[UUID],
        status: UserEstablishmentStatus,
    ) -> None:
        """Set the given user-establishment relations to the specified status."""
        await self.db.execute(
            update(UserEstablishment)
            .where(
                UserEstablishment.user_id == user_id,
                UserEstablishment.establishment_id.in_(establishment_ids),
            )
            .values(status=status)
        )
