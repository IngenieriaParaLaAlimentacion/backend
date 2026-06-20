import uuid
from unittest.mock import patch

import pytest
from fastapi import status
from sqlalchemy import select

import app.db.database as db_module
from app.core.security import create_access_token
from app.domain.user import UserRole, UserStatus
from app.models.user import User

pytestmark = pytest.mark.asyncio

INVITE_ADMIN_URL = "/api/v1/admin/invite-admin"


@pytest.fixture
def admin_headers():
    token = create_access_token(uuid.uuid4(), role=UserRole.ADMIN)
    return {"Authorization": f"Bearer {token}"}


def _invite_body(**overrides):
    return {"email": f"admin_{uuid.uuid4().hex[:6]}@test.com", **overrides}


class TestInviteAdminAuth:
    async def test_unauthenticated_returns_401(self, client):
        """Should return 401 if no token is provided."""
        response = await client.post(INVITE_ADMIN_URL, json=_invite_body())
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_manager_is_forbidden(self, client):
        """Should return 403 when a manager token is provided."""
        token = create_access_token(uuid.uuid4(), role=UserRole.ESTABLISHMENT_MANAGER)
        response = await client.post(
            INVITE_ADMIN_URL,
            json=_invite_body(),
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    async def test_professional_is_forbidden(self, client):
        """Should return 403 when a professional token is provided."""
        token = create_access_token(uuid.uuid4(), role=UserRole.PROFESSIONAL)
        response = await client.post(
            INVITE_ADMIN_URL,
            json=_invite_body(),
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN


class TestInviteAdminSuccess:
    async def test_returns_202(self, client, admin_headers):
        """Should return 202 Accepted on a valid invitation."""
        with patch("app.services.admin_service.send_invite_email"):
            response = await client.post(
                INVITE_ADMIN_URL, json=_invite_body(), headers=admin_headers
            )
        assert response.status_code == status.HTTP_202_ACCEPTED

    async def test_creates_user_in_db_with_admin_role(self, client, admin_headers):
        """The invited user should be persisted with role=ADMIN."""
        email = f"admin_{uuid.uuid4().hex[:6]}@test.com"

        with patch("app.services.admin_service.send_invite_email"):
            await client.post(
                INVITE_ADMIN_URL,
                json={"email": email},
                headers=admin_headers,
            )

        async with db_module.AsyncSessionLocal() as session:
            result = await session.execute(select(User).where(User.email == email))
            user = result.scalar_one()

        assert user.role == UserRole.ADMIN
        assert user.status == UserStatus.PENDING_VALIDATION

    async def test_sends_invite_email(self, client, admin_headers):
        """Should call send_invite_email once with the invited user's email."""
        email = f"admin_{uuid.uuid4().hex[:6]}@test.com"

        with patch("app.services.admin_service.send_invite_email") as mock_send:
            await client.post(
                INVITE_ADMIN_URL,
                json={"email": email},
                headers=admin_headers,
            )

        mock_send.assert_called_once()
        assert mock_send.call_args[0][0] == email

    async def test_response_body_is_empty(self, client, admin_headers):
        """202 response should have no body."""
        with patch("app.services.admin_service.send_invite_email"):
            response = await client.post(
                INVITE_ADMIN_URL, json=_invite_body(), headers=admin_headers
            )
        assert response.content == b""


class TestInviteAdminConflict:
    async def test_returns_409_if_email_already_registered(self, client, admin_headers):
        """Should return 409 if the email is already in use."""
        email = f"admin_{uuid.uuid4().hex[:6]}@test.com"

        with patch("app.services.admin_service.send_invite_email"):
            await client.post(
                INVITE_ADMIN_URL, json={"email": email}, headers=admin_headers
            )
            response = await client.post(
                INVITE_ADMIN_URL, json={"email": email}, headers=admin_headers
            )

        assert response.status_code == status.HTTP_409_CONFLICT

    async def test_does_not_create_duplicate_user(self, client, admin_headers):
        """Second invite for the same email should not create a second user."""
        email = f"admin_{uuid.uuid4().hex[:6]}@test.com"

        with patch("app.services.admin_service.send_invite_email"):
            await client.post(
                INVITE_ADMIN_URL, json={"email": email}, headers=admin_headers
            )
            await client.post(
                INVITE_ADMIN_URL, json={"email": email}, headers=admin_headers
            )

        async with db_module.AsyncSessionLocal() as session:
            result = await session.execute(select(User).where(User.email == email))
            users = result.scalars().all()

        assert len(users) == 1


class TestInviteAdminValidation:
    async def test_missing_email_returns_422(self, client, admin_headers):
        """Should return 422 if email field is missing."""
        response = await client.post(INVITE_ADMIN_URL, json={}, headers=admin_headers)
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    async def test_invalid_email_format_returns_422(self, client, admin_headers):
        """Should return 422 if email is not a valid format."""
        response = await client.post(
            INVITE_ADMIN_URL,
            json={"email": "not-an-email"},
            headers=admin_headers,
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
