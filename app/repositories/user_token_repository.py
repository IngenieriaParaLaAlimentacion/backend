from datetime import timedelta
from uuid import UUID

from sqlalchemy import func, select, update
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

    async def get_active_refresh_token(
        self, refresh_token_hash: str, device_id: UUID
    ) -> UserToken | None:
        """Retrieve a refresh token only if it is active.

        A token is considered active when it is bound to the device, not revoked,
        and not expired according to database time.
        """
        query = select(UserToken).where(
            UserToken.token_hash == refresh_token_hash,
            UserToken.device_id == device_id,
            UserToken.revoked.is_(False),
            UserToken.expires_at > func.now(),
        )

        result = await self.db.execute(query)
        return result.scalars().first()

    async def revoke(self, token: UserToken) -> None:
        """Mark a refresh token as revoked."""
        token.revoked = True

    async def revoke_all_by_user_id(self, user_id: UUID) -> int:
        """Revoke all active refresh tokens for a user."""
        result = await self.db.execute(
            update(UserToken)
            .where(
                UserToken.user_id == user_id,
                UserToken.revoked.is_(False),
            )
            .values(revoked=True)
            .execution_options(synchronize_session=False)
        )
        return result.rowcount
