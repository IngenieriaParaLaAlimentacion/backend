from datetime import timedelta
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.user_token import UserToken


def _expiry_expression():
    return func.now() + timedelta(days=settings.refresh_token_expire_days)


class TokenRepository:
    """Persistence operations for refresh token records."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self, user_id: UUID, token_hash: str, device_id: UUID, role: str
    ) -> UserToken:
        """Create and stage a refresh token record."""
        token = UserToken(
            user_id=user_id,
            token_hash=token_hash,
            device_id=device_id,
            role=role,
            expires_at=_expiry_expression(),
        )
        self.db.add(token)
        return token
