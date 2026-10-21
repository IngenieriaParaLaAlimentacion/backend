import uuid
from datetime import datetime, timedelta, timezone

from fastapi import status
from sqlalchemy import select, text

import app.db.database as db_module
from app.config.settings import settings
from app.core.security import create_password_recovery_token, hash_password
from app.domain.user import UserRole, UserStatus
from app.models.auth.password_recovery_token import PasswordRecoveryToken
from app.models.auth.user import User
from app.models.auth.user_password import UserPassword
from tests.integration.urls import LOGIN_URL

ACCEPT_INVITE_URL = "/api/v1/auth/invite/accept"


def _login_payload(email: str, password: str) -> dict:
    return {"email": email, "password": password, "device_id": str(uuid.uuid4())}


async def _insert_invited_user(
    role: UserRole,
    status_val: UserStatus = UserStatus.PENDING_VALIDATION,
) -> tuple[User, str]:
    """Helper: create user in DB and emit an invite recovery token."""
    plain_token, token_hash = create_password_recovery_token()
    user_id = uuid.uuid4()
    async with db_module.AsyncSessionLocal() as session:
        user = User(
            id=user_id,
            name="",
            last_name="",
            email=f"invited_{user_id.hex[:6]}@test.com",
            role=role,
            status=status_val,
        )
        session.add(user)
        await session.flush()
        session.add(
            UserPassword(
                user_id=user.id,
                password_hashed=hash_password("temp_password_123"),
            )
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


class TestAcceptInviteSuccess:
    async def test_pending_admin_accepts_invite_successfully(self, client):
        user, token = await _insert_invited_user(UserRole.ADMIN)

        payload = {
            "token": token,
            "new_password": "newpassword123",
            "name": "AdminName",
            "last_name": "AdminLastName",
            "locality": "La Plata",
            "description": "Admin bio info",
            "contact_phone": "+541198765432",
        }
        res = await client.post(ACCEPT_INVITE_URL, json=payload)
        assert res.status_code == status.HTTP_204_NO_CONTENT

        # Verify DB state
        async with db_module.AsyncSessionLocal() as session:
            result = await session.execute(select(User).where(User.id == user.id))
            updated_user = result.scalar_one()
            assert updated_user.status == UserStatus.ACTIVE
            assert updated_user.is_email_verified is True
            assert updated_user.name == "AdminName"
            assert updated_user.last_name == "AdminLastName"
            assert updated_user.locality == "La Plata"
            assert updated_user.description == "Admin bio info"
            assert updated_user.contact_phone == "+541198765432"

        # Verify new password works on login
        login_res = await client.post(
            LOGIN_URL, json=_login_payload(user.email, "newpassword123")
        )
        assert login_res.status_code == status.HTTP_200_OK

    async def test_pending_analyst_accepts_invite_successfully(self, client):
        user, token = await _insert_invited_user(UserRole.ANALYST)

        payload = {
            "token": token,
            "new_password": "analystpassword123",
            "name": "AnalystName",
            "last_name": "AnalystLastName",
        }
        res = await client.post(ACCEPT_INVITE_URL, json=payload)
        assert res.status_code == status.HTTP_204_NO_CONTENT

        async with db_module.AsyncSessionLocal() as session:
            result = await session.execute(select(User).where(User.id == user.id))
            updated_user = result.scalar_one()
            assert updated_user.status == UserStatus.ACTIVE
            assert updated_user.is_email_verified is True
            assert updated_user.name == "AnalystName"
            assert updated_user.last_name == "AnalystLastName"
            assert updated_user.locality is None
            assert updated_user.description is None
            assert updated_user.contact_phone is None

        login_res = await client.post(
            LOGIN_URL, json=_login_payload(user.email, "analystpassword123")
        )
        assert login_res.status_code == status.HTTP_200_OK


class TestAcceptInviteRejections:
    async def test_field_worker_token_rejected_with_400(self, client):
        user, token = await _insert_invited_user(UserRole.FIELD_WORKER)

        payload = {
            "token": token,
            "new_password": "newpassword123",
            "name": "FieldName",
            "last_name": "FieldLast",
        }
        res = await client.post(ACCEPT_INVITE_URL, json=payload)
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert res.json()["type"] == "/errors/auth/invalid-recovery-token"

    async def test_active_user_token_rejected_with_400(self, client):
        user, token = await _insert_invited_user(
            UserRole.ADMIN, status_val=UserStatus.ACTIVE
        )

        payload = {
            "token": token,
            "new_password": "newpassword123",
            "name": "AdminName",
            "last_name": "AdminLast",
        }
        res = await client.post(ACCEPT_INVITE_URL, json=payload)
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert res.json()["type"] == "/errors/auth/invalid-recovery-token"

    async def test_unknown_token_rejected_with_400(self, client):
        payload = {
            "token": "completely-unknown-token",
            "new_password": "newpassword123",
            "name": "SomeName",
            "last_name": "SomeLast",
        }
        res = await client.post(ACCEPT_INVITE_URL, json=payload)
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert res.json()["type"] == "/errors/auth/invalid-recovery-token"

    async def test_used_token_rejected_with_400(self, client):
        user, token = await _insert_invited_user(UserRole.ADMIN)

        payload = {
            "token": token,
            "new_password": "newpassword123",
            "name": "AdminName",
            "last_name": "AdminLast",
        }
        first_res = await client.post(ACCEPT_INVITE_URL, json=payload)
        assert first_res.status_code == status.HTTP_204_NO_CONTENT

        # Second attempt with the same token must fail with 400
        second_res = await client.post(ACCEPT_INVITE_URL, json=payload)
        assert second_res.status_code == status.HTTP_400_BAD_REQUEST
        assert second_res.json()["type"] == "/errors/auth/invalid-recovery-token"

    async def test_expired_token_rejected_with_400(self, client):
        user, token = await _insert_invited_user(UserRole.ADMIN)

        async with db_module.engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE password_recovery_tokens "
                    "SET expires_at = now() - interval '1 hour'"
                )
            )

        payload = {
            "token": token,
            "new_password": "newpassword123",
            "name": "AdminName",
            "last_name": "AdminLast",
        }
        res = await client.post(ACCEPT_INVITE_URL, json=payload)
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert res.json()["type"] == "/errors/auth/invalid-recovery-token"


class TestAcceptInviteValidation:
    async def test_missing_name_returns_422(self, client):
        res = await client.post(
            ACCEPT_INVITE_URL,
            json={
                "token": "sometoken",
                "new_password": "newpassword123",
                "last_name": "LastName",
            },
        )
        assert res.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_short_password_returns_422(self, client):
        res = await client.post(
            ACCEPT_INVITE_URL,
            json={
                "token": "sometoken",
                "new_password": "short",
                "name": "Name",
                "last_name": "LastName",
            },
        )
        assert res.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_invalid_phone_pattern_returns_422(self, client):
        res = await client.post(
            ACCEPT_INVITE_URL,
            json={
                "token": "sometoken",
                "new_password": "newpassword123",
                "name": "Name",
                "last_name": "LastName",
                "contact_phone": "invalid-phone-abc",
            },
        )
        assert res.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
