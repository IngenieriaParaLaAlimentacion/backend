from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth.email_verification_token import EmailVerificationToken


class EmailVerificationTokenRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        user_id: UUID,
        token_hash: str,
        expires_delta: timedelta,
    ) -> EmailVerificationToken:
        """Create and stage an email verification token record."""
        token = EmailVerificationToken(
            user_id=user_id,
            token_hash=token_hash,
            expires_at=datetime.now(timezone.utc) + expires_delta,
        )
        self.db.add(token)
        await self.db.flush()
        await self.db.refresh(token)
        return token

    async def get_active_token(self, token_hash: str) -> EmailVerificationToken | None:
        """Return an active, unused, non-expired token by hash, or None."""
        result = await self.db.execute(
            select(EmailVerificationToken).where(
                EmailVerificationToken.token_hash == token_hash,
                EmailVerificationToken.used.is_(False),
                EmailVerificationToken.expires_at > func.now(),
            )
        )
        return result.scalar_one_or_none()

    async def mark_used(self, token: EmailVerificationToken) -> None:
        """Mark a verification token as consumed."""
        token.used = True

    async def revoke_active_for_user(self, user_id: UUID) -> int:
        """Mark all active verification tokens for a user as used.

        Returns the number of tokens revoked.
        """
        result = await self.db.execute(
            update(EmailVerificationToken)
            .where(
                EmailVerificationToken.user_id == user_id,
                EmailVerificationToken.used.is_(False),
                EmailVerificationToken.expires_at > func.now(),
            )
            .values(used=True)
            .execution_options(synchronize_session=False)
        )
        return result.rowcount
