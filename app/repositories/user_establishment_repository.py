import uuid
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_establishment import UserEstablishment, UserEstablishmentStatus


class UserEstablishmentRepository:
    """Persistence operations for UserEstablishment association records."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def preset_relation(
        self, user_id: uuid.UUID, establishment_id: uuid.UUID
    ) -> UserEstablishment:
        """Stage a pending user-establishment relation for a manager registration."""
        status = UserEstablishmentStatus.PENDING
        user_establishment = UserEstablishment(
            user_id=user_id, establishment_id=establishment_id, status=status
        )
        self.db.add(user_establishment)
        return user_establishment

    async def get_by_user_ids(self, user_ids: list[UUID]) -> dict[UUID, list[UUID]]:
        """Return a mapping of user_id → list of establishment_ids for
        the given users."""
        if not user_ids:
            return {}
        result = await self.db.execute(
            select(UserEstablishment.user_id, UserEstablishment.establishment_id).where(
                UserEstablishment.user_id.in_(user_ids)
            )
        )
        mapping: dict[UUID, list[UUID]] = {uid: [] for uid in user_ids}
        for user_id, estab_id in result.all():
            mapping[user_id].append(estab_id)
        return mapping

    async def get_by_user_id(self, user_id: UUID) -> list[UserEstablishment]:
        """Return all UserEstablishment records for a given user."""
        result = await self.db.execute(
            select(UserEstablishment).where(UserEstablishment.user_id == user_id)
        )
        return list(result.scalars().all())
