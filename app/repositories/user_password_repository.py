from sqlalchemy.ext.asyncio import AsyncSession


class UserPasswordRepository:
    """Persistence operations for user password records."""

    def __init__(self, db: AsyncSession):
        self.db = db