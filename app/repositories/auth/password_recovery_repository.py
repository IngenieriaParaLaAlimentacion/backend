from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.password_recovery_token import PasswordRecoveryToken


class PasswordRecoveryTokenRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        user_id: UUID,
        token_hash: str,
        expires_delta: timedelta,
    ) -> PasswordRecoveryToken:
        """Create and stage a password recovery token record."""
        token = PasswordRecoveryToken(
            user_id=user_id,
            token_hash=token_hash,
            expires_at=datetime.now(timezone.utc) + expires_delta,
        )
        self.db.add(token)
        await self.db.flush()
        await self.db.refresh(token)
        return token

    async def revoke_active_for_user(self, user_id: UUID) -> int:
        """Mark all active recovery tokens for a user as used.

        Returns the number of tokens revoked.
        """
        result = await self.db.execute(
            update(PasswordRecoveryToken)
            .where(
                PasswordRecoveryToken.user_id == user_id,
                PasswordRecoveryToken.used.is_(False),
                PasswordRecoveryToken.expires_at > func.now(),
            )
            .values(used=True)
            .execution_options(synchronize_session=False)
        )
        return result.rowcount

    async def mark_used(self, token: PasswordRecoveryToken) -> None:
        """Mark a recovery token as used."""
        token.used = True

    async def get_active_token(self, token_hash: str) -> PasswordRecoveryToken | None:
        """Return an active recovery token by hash, or None."""
        result = await self.db.execute(
            select(PasswordRecoveryToken).where(
                PasswordRecoveryToken.token_hash == token_hash,
                PasswordRecoveryToken.used.is_(False),
                PasswordRecoveryToken.expires_at > func.now(),
            )
        )
        return result.scalar_one_or_none()
