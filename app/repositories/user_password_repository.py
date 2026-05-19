from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions.domain_exceptions import PasswordNotFoundError
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

    async def get_by_user_id(self, user_id: UUID) -> UserPassword:
        """Return password row for a user or raise PasswordNotFoundError."""
        query = select(UserPassword).where(UserPassword.user_id == user_id)
        result = await self.db.execute(query)
        password = result.scalar_one_or_none()
        if not password:
            raise PasswordNotFoundError(str(user_id))
        return password
