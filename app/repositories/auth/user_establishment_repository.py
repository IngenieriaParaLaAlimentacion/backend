from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.establishment import UserEstablishmentStatus
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

    async def approve_relations(
        self, user_id: UUID, establishment_ids: list[UUID]
    ) -> None:
        """Grant the user approved access to each of the given establishments.

        Inserts missing relations as approved and flips existing ones in any
        other status to approved, so no duplicate row is ever created.
        """
        stmt = insert(UserEstablishment).values(
            [
                {
                    "user_id": user_id,
                    "establishment_id": establishment_id,
                    "status": UserEstablishmentStatus.APPROVED,
                }
                for establishment_id in establishment_ids
            ]
        )
        # An upsert keeps a concurrent subscribe to the same pair from failing.
        await self.db.execute(
            stmt.on_conflict_do_update(
                index_elements=[
                    UserEstablishment.user_id,
                    UserEstablishment.establishment_id,
                ],
                set_={"status": stmt.excluded.status},
            )
        )

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

    async def delete_relations(
        self, user_id: UUID, establishment_ids: list[UUID]
    ) -> None:
        """Delete the user's relations to the given establishments, if any."""
        await self.db.execute(
            delete(UserEstablishment).where(
                UserEstablishment.user_id == user_id,
                UserEstablishment.establishment_id.in_(establishment_ids),
            )
        )

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
