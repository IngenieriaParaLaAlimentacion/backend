from datetime import timedelta
from uuid import UUID

from sqlalchemy import func, update
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
        """Create and stage a password recovery token record.

        The timestamp source is the database clock (func.now()).
        """
        token = PasswordRecoveryToken(
            user_id=user_id,
            token_hash=token_hash,
            expires_at=func.now() + expires_delta,
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
