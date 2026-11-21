from datetime import timedelta
from uuid import UUID

from sqlalchemy import Select, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import settings
from app.models.auth.user_token import UserToken


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

    def _refresh_candidates(
        self, token_hash: str, device_id: UUID, *, report_user_blocked: bool
    ) -> Select[tuple[UserToken]]:
        active = UserToken.revoked.is_(False)
        candidate = (
            or_(active, UserToken.revoked_for_block.is_(True))
            if report_user_blocked
            else active
        )
        return select(UserToken).where(
            UserToken.token_hash == token_hash,
            UserToken.device_id == device_id,
            UserToken.expires_at > func.statement_timestamp(),
            candidate,
        )

    async def get_refresh_candidate_user_id(
        self, token_hash: str, device_id: UUID, *, report_user_blocked: bool = False
    ) -> UUID | None:
        """Look up the credential's candidate owner without locking the token."""
        query = self._refresh_candidates(
            token_hash, device_id, report_user_blocked=report_user_blocked
        ).with_only_columns(UserToken.user_id)
        result = await self.db.execute(query)
        return result.scalars().first()

    async def get_refresh_candidate(
        self, token_hash: str, device_id: UUID, *, report_user_blocked: bool = False
    ) -> UserToken | None:
        """Recheck and lock the credential after the caller has locked its user."""
        query = (
            self._refresh_candidates(
                token_hash, device_id, report_user_blocked=report_user_blocked
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        result = await self.db.execute(query)
        return result.scalars().first()

    async def revoke_all_by_user_id(
        self, user_id: UUID, *, for_block: bool = False
    ) -> int:
        """Revoke all unrevoked refresh tokens and mark unexpired ones for a block."""
        query = update(UserToken).where(
            UserToken.user_id == user_id,
            UserToken.revoked.is_(False),
        )
        if for_block:
            query = query.values(
                revoked=True,
                revoked_for_block=UserToken.expires_at > func.statement_timestamp(),
            )
        else:
            query = query.values(revoked=True)
        result = await self.db.execute(
            query.execution_options(synchronize_session=False)
        )
        return result.rowcount

    async def clear_block_revocation_by_user_id(self, user_id: UUID) -> None:
        """Clear the user's block revocation markers."""
        query = (
            update(UserToken)
            .where(UserToken.user_id == user_id, UserToken.revoked_for_block.is_(True))
            .values(revoked_for_block=False)
            .execution_options(synchronize_session=False)
        )
        await self.db.execute(query)
