from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.user_block_event import UserBlockEventType
from app.models.auth.user_block_event import UserBlockEvent


class UserBlockEventRepository:
    """Persistence of the audit log of user blocks."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def append(
        self,
        *,
        user_id: UUID,
        actor_id: UUID,
        event_type: UserBlockEventType,
    ) -> None:
        """Persist a new block or unblock event to the audit log."""
        self.db.add(
            UserBlockEvent(user_id=user_id, actor_id=actor_id, event_type=event_type)
        )
        await self.db.flush()
