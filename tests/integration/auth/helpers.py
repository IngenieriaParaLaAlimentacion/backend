import uuid
from datetime import datetime, timedelta, timezone

import app.db.database as db_module
from app.config.settings import settings
from app.core.security import create_password_recovery_token, hash_password
from app.domain.user import UserRole, UserStatus
from app.models.auth.password_recovery_token import PasswordRecoveryToken
from app.models.auth.user import User
from app.models.auth.user_password import UserPassword


async def insert_user_with_recovery_token(
    role: UserRole, user_status: UserStatus = UserStatus.PENDING_VALIDATION
) -> tuple[User, str]:
    """Create a user with a password and an unused recovery token.

    Returns the user and the plain token, as an invite or recovery email would
    carry it.
    """
    plain_token, token_hash = create_password_recovery_token()
    user_id = uuid.uuid4()
    async with db_module.AsyncSessionLocal() as session:
        user = User(
            id=user_id,
            name="",
            last_name="",
            email=f"{user_id}@test.com",
            role=role,
            status=user_status,
        )
        session.add(user)
        await session.flush()
        session.add(
            UserPassword(user_id=user.id, password_hashed=hash_password("oldpass123"))
        )
        session.add(
            PasswordRecoveryToken(
                user_id=user.id,
                token_hash=token_hash,
                expires_at=datetime.now(timezone.utc)
                + timedelta(minutes=settings.password_recovery_token_expire_minutes),
                used=False,
            )
        )
        await session.commit()
        await session.refresh(user)
    return user, plain_token
