from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.email_verification_token import EmailVerificationToken


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
