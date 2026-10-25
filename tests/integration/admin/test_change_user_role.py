import uuid
from unittest.mock import AsyncMock, patch

import aiosmtplib
import pytest
import pytest_asyncio
from fastapi import status
from sqlalchemy import select

import app.db.database as db_module
from app.config.settings import settings
from app.domain.user import UserRole, UserStatus
from app.models.auth.user import User
from app.models.auth.user_token import UserToken
from tests.integration.admin.conftest import _insert_user

CHANGE_ROLE_URL = "/api/v1/admin/users/{user_id}/role"
SEND_MAIL = "app.services.admin_service.send_role_changed_email"


async def _change_role(client, headers, user_id, role):
    return await client.patch(
        CHANGE_ROLE_URL.format(user_id=user_id), json={"role": role}, headers=headers
    )


async def _get_role(user_id: uuid.UUID) -> UserRole:
    async with db_module.AsyncSessionLocal() as session:
        user = await session.get(User, user_id)
        return user.role


async def _insert_refresh_token(user_id: uuid.UUID, role: UserRole) -> uuid.UUID:
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


async def _is_revoked(token_id: uuid.UUID) -> bool:
    async with db_module.AsyncSessionLocal() as session:
        result = await session.execute(
            select(UserToken.revoked).where(UserToken.id == token_id)
        )
        return result.scalar_one()


@pytest_asyncio.fixture
async def admin(make_user_with_role):
    headers, _ = await make_user_with_role(UserRole.ADMIN)
    return headers


@pytest_asyncio.fixture
async def superadmin(make_user_with_role):
    return await make_user_with_role(UserRole.SUPERADMIN)


class TestChangeUserRoleAllowed:
    @pytest.mark.parametrize(
        ("old_role", "new_role"),
        [
            (UserRole.FIELD_WORKER, UserRole.ANALYST),
            (UserRole.ANALYST, UserRole.ADMIN),
        ],
    )
    async def test_admin_changes_role(self, client, admin, old_role, new_role):
        user_id = await _insert_user(old_role, UserStatus.ACTIVE)

        with patch(SEND_MAIL) as send_mail:
            response = await _change_role(client, admin, user_id, new_role.value)

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["id"] == str(user_id)
        assert body["role"] == new_role.value
        assert await _get_role(user_id) == new_role
        send_mail.assert_awaited_once_with(
            f"{user_id}@test.com", old_role, new_role, "Test"
        )

    async def test_superadmin_demotes_admin(self, client, superadmin):
        headers, _ = superadmin
        user_id = await _insert_user(UserRole.ADMIN, UserStatus.ACTIVE)

        with patch(SEND_MAIL):
            response = await _change_role(
                client, headers, user_id, UserRole.ANALYST.value
            )

        assert response.status_code == status.HTTP_200_OK
        assert await _get_role(user_id) == UserRole.ANALYST

    async def test_revokes_refresh_tokens(self, client, admin):
        user_id = await _insert_user(UserRole.FIELD_WORKER, UserStatus.ACTIVE)
        token_id = await _insert_refresh_token(user_id, UserRole.FIELD_WORKER)

        with patch(SEND_MAIL):
            await _change_role(client, admin, user_id, UserRole.ANALYST.value)

        assert await _is_revoked(token_id)

    async def test_same_role_is_noop(self, client, admin):
        user_id = await _insert_user(UserRole.ANALYST, UserStatus.ACTIVE)
        token_id = await _insert_refresh_token(user_id, UserRole.ANALYST)

        with patch(SEND_MAIL) as send_mail:
            response = await _change_role(
                client, admin, user_id, UserRole.ANALYST.value
            )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["role"] == UserRole.ANALYST.value
        send_mail.assert_not_called()
        assert not await _is_revoked(token_id)

    async def test_smtp_failure_keeps_role_change(self, client, admin, monkeypatch):
        monkeypatch.setattr(settings, "smtp_enabled", True)
        user_id = await _insert_user(UserRole.FIELD_WORKER, UserStatus.ACTIVE)

        with patch(
            "app.services.email_service.aiosmtplib.send",
            AsyncMock(side_effect=aiosmtplib.SMTPException("down")),
        ):
            response = await _change_role(
                client, admin, user_id, UserRole.ANALYST.value
            )

        assert response.status_code == status.HTTP_200_OK
        assert await _get_role(user_id) == UserRole.ANALYST


class TestChangeUserRoleForbidden:
    async def test_admin_cannot_change_admin(self, client, admin):
        user_id = await _insert_user(UserRole.ADMIN, UserStatus.ACTIVE)

        response = await _change_role(client, admin, user_id, UserRole.ANALYST.value)

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.json()["type"] == "/errors/role-not-allowed"
        assert await _get_role(user_id) == UserRole.ADMIN

    @pytest.mark.parametrize("actor_role", [UserRole.ADMIN, UserRole.SUPERADMIN])
    async def test_nobody_changes_superadmin(
        self, client, make_user_with_role, actor_role
    ):
        headers, _ = await make_user_with_role(actor_role)
        user_id = await _insert_user(UserRole.SUPERADMIN, UserStatus.ACTIVE)

        response = await _change_role(client, headers, user_id, UserRole.ADMIN.value)

        assert response.status_code == status.HTTP_403_FORBIDDEN

    async def test_cannot_change_own_role(self, client, superadmin):
        headers, user_id = superadmin

        response = await _change_role(client, headers, user_id, UserRole.ADMIN.value)

        assert response.status_code == status.HTTP_403_FORBIDDEN


class TestChangeUserRoleInvalid:
    async def test_superadmin_role_rejected(self, client, superadmin):
        headers, _ = superadmin
        user_id = await _insert_user(UserRole.ADMIN, UserStatus.ACTIVE)

        response = await _change_role(
            client, headers, user_id, UserRole.SUPERADMIN.value
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_pending_user_rejected(self, client, admin):
        user_id = await _insert_user(
            UserRole.FIELD_WORKER, UserStatus.PENDING_VALIDATION
        )

        response = await _change_role(client, admin, user_id, UserRole.ANALYST.value)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["type"] == "/errors/user-is-not-active"

    async def test_unknown_user_returns_404(self, client, admin):
        response = await _change_role(
            client, admin, uuid.uuid4(), UserRole.ANALYST.value
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND
