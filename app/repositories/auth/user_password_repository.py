from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import UserPassword


class UserPasswordRepository:
    """Persistence operations for user password records."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, user_id: UUID, password_hashed: str) -> UserPassword:
        """Create and stage a password hash row for a user."""
        password = UserPassword(user_id=user_id, password_hashed=password_hashed)
        self.db.add(password)
        return password

    async def get_by_user_id(self, user_id: UUID) -> UserPassword | None:
        """Return the password row for a user, or None.

        Returns None rather than raising: on the login path a missing row must
        surface as a 401, not as a 404 naming the user's id, which would let the
        endpoint be used to enumerate registered addresses.
        """
        query = select(UserPassword).where(UserPassword.user_id == user_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()
