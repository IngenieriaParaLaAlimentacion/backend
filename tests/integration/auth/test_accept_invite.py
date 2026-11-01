import uuid

import pytest
from fastapi import status
from sqlalchemy import select, text

import app.db.database as db_module
from app.domain.user import UserRole, UserStatus
from app.models.auth.user import User
from tests.integration.auth.helpers import insert_user_with_recovery_token
from tests.integration.urls import LOGIN_URL

ACCEPT_INVITE_URL = "/api/v1/auth/invite/accept"


def _payload(token: str, **overrides) -> dict:
    return {
        "token": token,
        "new_password": "newpassword123",
        "name": "Ana",
        "last_name": "Gomez",
        **overrides,
    }


async def _fetch_user(user_id: uuid.UUID) -> User:
    async with db_module.AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        return result.scalar_one()


class TestAcceptInviteSuccess:
    @pytest.mark.parametrize("role", [UserRole.ADMIN, UserRole.ANALYST])
    async def test_pending_invitee_is_activated_with_profile(self, client, role):
        user, token = await insert_user_with_recovery_token(role)

        res = await client.post(
            ACCEPT_INVITE_URL,
            json=_payload(
                token,
                locality="La Plata",
                description="Bio",
                contact_phone="+541198765432",
            ),
        )
        assert res.status_code == status.HTTP_204_NO_CONTENT

        stored = await _fetch_user(user.id)
        assert stored.status == UserStatus.ACTIVE
        assert stored.is_email_verified is True
        assert (stored.name, stored.last_name) == ("Ana", "Gomez")
        assert (stored.locality, stored.description, stored.contact_phone) == (
            "La Plata",
            "Bio",
            "+541198765432",
        )

        login_res = await client.post(
            LOGIN_URL,
            json={
                "email": user.email,
                "password": "newpassword123",
                "device_id": str(uuid.uuid4()),
            },
        )
        assert login_res.status_code == status.HTTP_200_OK


class TestAcceptInviteRejections:
    @pytest.mark.parametrize(
        ("role", "user_status"),
        [
            (UserRole.FIELD_WORKER, UserStatus.PENDING_VALIDATION),
            (UserRole.ADMIN, UserStatus.ACTIVE),
        ],
    )
    async def test_user_not_pending_invitee_returns_401(
        self, client, role, user_status
    ):
        user, token = await insert_user_with_recovery_token(role, user_status)

        res = await client.post(ACCEPT_INVITE_URL, json=_payload(token))
        assert res.status_code == status.HTTP_401_UNAUTHORIZED
        assert res.json()["type"] == "/errors/auth/invalid-recovery-token"
        assert (await _fetch_user(user.id)).status == user_status

    async def test_unknown_token_returns_401(self, client):
        res = await client.post(ACCEPT_INVITE_URL, json=_payload("unknown-token"))
        assert res.status_code == status.HTTP_401_UNAUTHORIZED
        assert res.json()["type"] == "/errors/auth/invalid-recovery-token"

    async def test_used_token_returns_401(self, client):
        _, token = await insert_user_with_recovery_token(UserRole.ADMIN)
        await client.post(ACCEPT_INVITE_URL, json=_payload(token))

        res = await client.post(ACCEPT_INVITE_URL, json=_payload(token))
        assert res.status_code == status.HTTP_401_UNAUTHORIZED
        assert res.json()["type"] == "/errors/auth/recovery-token-used"

    async def test_expired_token_returns_401(self, client):
        _, token = await insert_user_with_recovery_token(UserRole.ADMIN)
        async with db_module.engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE password_recovery_tokens "
                    "SET expires_at = now() - interval '1 hour'"
                )
            )

        res = await client.post(ACCEPT_INVITE_URL, json=_payload(token))
        assert res.status_code == status.HTTP_401_UNAUTHORIZED
        assert res.json()["type"] == "/errors/auth/recovery-token-expired"

    @pytest.mark.parametrize("field", ["name", "last_name"])
    async def test_missing_required_profile_field_returns_422(self, client, field):
        body = _payload("sometoken")
        del body[field]

        res = await client.post(ACCEPT_INVITE_URL, json=body)
        assert res.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
