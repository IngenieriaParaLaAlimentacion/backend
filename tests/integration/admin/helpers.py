"""Helpers shared by the admin integration tests."""

import uuid

from sqlalchemy import select

import app.db.database as db_module
from app.domain.user import UserRole
from app.models.auth.user_token import UserToken


async def insert_refresh_token(user_id: uuid.UUID, role: UserRole) -> uuid.UUID:
    """Insert an unrevoked refresh token for the user and return its id."""
    token_id = uuid.uuid4()
    async with db_module.AsyncSessionLocal() as session:
        session.add(
            UserToken(
                id=token_id,
                user_id=user_id,
                device_id=uuid.uuid4(),
                role=role,
                token_hash=uuid.uuid4().hex,
            )
        )
        await session.commit()
    return token_id


async def is_revoked(token_id: uuid.UUID) -> bool:
    """Return whether the refresh token has been revoked."""
    async with db_module.AsyncSessionLocal() as session:
        result = await session.execute(
            select(UserToken.revoked).where(UserToken.id == token_id)
        )
        return result.scalar_one()
