import uuid

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
