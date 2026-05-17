from sqlalchemy.ext.asyncio import AsyncSession


class TokenRepository:
    """Persistence operations for refresh token records."""

    def __init__(self, db: AsyncSession):
        self.db = db