import uuid
from unittest.mock import patch

from fastapi import status
from sqlalchemy import func, select

import app.db.database as db_module
from app.core.security import create_access_token
from app.domain.user import UserRole, UserStatus
from app.exceptions.domain_exceptions import EmailDeliveryError
from app.models.auth.user import User
from tests.integration.urls import INVITE_ADMIN_URL

INVITE_ANALYST_URL = "/api/v1/admin/invite-analyst"
RESEND_INVITE_URL = "/api/v1/admin/users/{user_id}/resend-invite"


def _invite_body(**overrides):
    return {"email": f"admin_{uuid.uuid4().hex[:6]}@test.com", **overrides}


async def _create_pending_admin(client, admin_headers) -> tuple[str, str]:
    """Helper: invites a new admin and returns (user_id, email)."""
    email = f"admin_{uuid.uuid4().hex[:6]}@test.com"
    with patch("app.services.admin_service.send_invite_email"):
        await client.post(
            INVITE_ADMIN_URL, json={"email": email}, headers=admin_headers
        )

    async with db_module.AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.email == email))
        user = result.scalar_one()

    return str(user.id), email


class TestInviteAdminAuth:
    async def test_unauthenticated_returns_401(self, client):
        """Should return 401 if no token is provided."""
        response = await client.post(INVITE_ADMIN_URL, json=_invite_body())
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_field_worker_is_forbidden(self, client):
        """Should return 403 when a field worker token is provided."""
        token = create_access_token(uuid.uuid4(), role=UserRole.FIELD_WORKER)
        response = await client.post(
            INVITE_ADMIN_URL,
            json=_invite_body(),
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    async def test_analyst_is_forbidden(self, client):
        """Should return 403 when an analyst token is provided."""
        token = create_access_token(uuid.uuid4(), role=UserRole.ANALYST)
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

    async def test_response_returns_created_user_id(self, client, admin_headers):
        """202 response should carry the created user's id in the body."""
        email = f"admin_{uuid.uuid4().hex[:6]}@test.com"

        with patch("app.services.admin_service.send_invite_email"):
            response = await client.post(
                INVITE_ADMIN_URL, json={"email": email}, headers=admin_headers
            )

        async with db_module.AsyncSessionLocal() as session:
            result = await session.execute(select(User).where(User.email == email))
            user = result.scalar_one()

        body = response.json()
        assert body == {"user_id": str(user.id)}


class TestInviteAnalystSuccess:
    async def test_returns_202_with_created_user_id(self, client, admin_headers):
        """Analyst invite should return 202 and the created user's id."""
        email = f"analyst_{uuid.uuid4().hex[:6]}@test.com"

        with patch("app.services.admin_service.send_invite_email"):
            response = await client.post(
                INVITE_ANALYST_URL, json={"email": email}, headers=admin_headers
            )

        assert response.status_code == status.HTTP_202_ACCEPTED

        async with db_module.AsyncSessionLocal() as session:
            result = await session.execute(select(User).where(User.email == email))
            user = result.scalar_one()

        assert user.role == UserRole.ANALYST
        assert response.json() == {"user_id": str(user.id)}


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

    async def test_pending_invitee_is_distinguishable_and_carries_user_id(
        self, client, admin_headers
    ):
        """Re-inviting a still-pending address must not look like an
        already-registered one, and must return the id resend-invite needs."""
        user_id, email = await _create_pending_admin(client, admin_headers)

        with patch("app.services.admin_service.send_invite_email"):
            response = await client.post(
                INVITE_ADMIN_URL, json={"email": email}, headers=admin_headers
            )

        assert response.status_code == status.HTTP_409_CONFLICT
        body = response.json()
        assert body["type"] == "/errors/admin/invite-already-pending"
        assert body["user_id"] == user_id

    async def test_returned_user_id_works_against_resend_invite(
        self, client, admin_headers
    ):
        _, email = await _create_pending_admin(client, admin_headers)

        with patch("app.services.admin_service.send_invite_email"):
            conflict = await client.post(
                INVITE_ADMIN_URL, json={"email": email}, headers=admin_headers
            )
            response = await client.patch(
                RESEND_INVITE_URL.format(user_id=conflict.json()["user_id"]),
                headers=admin_headers,
            )

        assert response.status_code == status.HTTP_202_ACCEPTED

    async def test_registered_user_reports_already_exists_without_user_id(
        self, client, admin_headers, db_active_user
    ):
        """An onboarded account is a different condition: resend-invite would
        not help, so no user_id is offered."""
        with patch("app.services.admin_service.send_invite_email"):
            response = await client.post(
                INVITE_ADMIN_URL,
                json={"email": db_active_user.email},
                headers=admin_headers,
            )

        assert response.status_code == status.HTTP_409_CONFLICT
        body = response.json()
        assert body["type"] == "/errors/user-already-exists"
        assert "user_id" not in body

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

    async def test_returns_409_if_email_differs_only_in_case(
        self, client, admin_headers
    ):
        """Casing must not bypass the duplicate check."""
        email = f"admin_{uuid.uuid4().hex[:6]}@test.com"

        with patch("app.services.admin_service.send_invite_email"):
            await client.post(
                INVITE_ADMIN_URL, json={"email": email}, headers=admin_headers
            )
            response = await client.post(
                INVITE_ADMIN_URL,
                json={"email": email.upper()},
                headers=admin_headers,
            )

        assert response.status_code == status.HTTP_409_CONFLICT

    async def test_case_variant_does_not_create_duplicate_user(
        self, client, admin_headers
    ):
        """An upper-cased retry must not end up as a second account."""
        email = f"admin_{uuid.uuid4().hex[:6]}@test.com"

        with patch("app.services.admin_service.send_invite_email"):
            await client.post(
                INVITE_ADMIN_URL, json={"email": email}, headers=admin_headers
            )
            await client.post(
                INVITE_ADMIN_URL,
                json={"email": email.upper()},
                headers=admin_headers,
            )

        async with db_module.AsyncSessionLocal() as session:
            result = await session.execute(
                select(User).where(func.lower(User.email) == email.lower())
            )
            users = result.scalars().all()

        assert len(users) == 1

    async def test_analyst_invite_returns_409_if_email_registered(
        self, client, admin_headers
    ):
        """The conflict must also surface on the analyst endpoint."""
        email = f"analyst_{uuid.uuid4().hex[:6]}@test.com"

        with patch("app.services.admin_service.send_invite_email"):
            await client.post(
                INVITE_ANALYST_URL, json={"email": email}, headers=admin_headers
            )
            response = await client.post(
                INVITE_ANALYST_URL, json={"email": email}, headers=admin_headers
            )

        assert response.status_code == status.HTTP_409_CONFLICT


class TestInviteAdminEmailFailure:
    async def test_returns_502_when_email_delivery_fails(self, client, admin_headers):
        """A failed invite email should surface as 502, not a false 202."""
        with patch(
            "app.services.admin_service.send_invite_email",
            side_effect=EmailDeliveryError(),
        ):
            response = await client.post(
                INVITE_ADMIN_URL, json=_invite_body(), headers=admin_headers
            )

        assert response.status_code == status.HTTP_502_BAD_GATEWAY

    async def test_account_persists_for_resend_when_email_fails(
        self, client, admin_headers
    ):
        """Even though delivery failed, the pending account is committed so the
        admin can recover via resend-invite."""
        email = f"admin_{uuid.uuid4().hex[:6]}@test.com"

        with patch(
            "app.services.admin_service.send_invite_email",
            side_effect=EmailDeliveryError(),
        ):
            await client.post(
                INVITE_ADMIN_URL, json={"email": email}, headers=admin_headers
            )

        async with db_module.AsyncSessionLocal() as session:
            result = await session.execute(select(User).where(User.email == email))
            user = result.scalar_one()

        assert user.status == UserStatus.PENDING_VALIDATION


class TestInviteAdminValidation:
    async def test_missing_email_returns_422(self, client, admin_headers):
        """Should return 422 if email field is missing."""
        response = await client.post(INVITE_ADMIN_URL, json={}, headers=admin_headers)
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_invalid_email_format_returns_422(self, client, admin_headers):
        """Should return 422 if email is not a valid format."""
        response = await client.post(
            INVITE_ADMIN_URL,
            json={"email": "not-an-email"},
            headers=admin_headers,
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


class TestResendInviteAuth:
    async def test_unauthenticated_returns_401(self, client):
        """Should return 401 if no token is provided."""
        response = await client.patch(RESEND_INVITE_URL.format(user_id=uuid.uuid4()))
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_field_worker_is_forbidden(self, client):
        """Should return 403 when a field worker token is provided."""
        token = create_access_token(uuid.uuid4(), role=UserRole.FIELD_WORKER)
        response = await client.patch(
            RESEND_INVITE_URL.format(user_id=uuid.uuid4()),
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    async def test_analyst_is_forbidden(self, client):
        """Should return 403 when an analyst token is provided."""
        token = create_access_token(uuid.uuid4(), role=UserRole.ANALYST)
        response = await client.patch(
            RESEND_INVITE_URL.format(user_id=uuid.uuid4()),
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN


class TestResendInviteSuccess:
    async def test_returns_202(self, client, admin_headers):
        """Should return 202 Accepted when re-inviting a pending user."""
        user_id, _ = await _create_pending_admin(client, admin_headers)

        with patch("app.services.admin_service.send_invite_email"):
            response = await client.patch(
                RESEND_INVITE_URL.format(user_id=user_id), headers=admin_headers
            )

        assert response.status_code == status.HTTP_202_ACCEPTED

    async def test_sends_invite_email_again(self, client, admin_headers):
        """Should call send_invite_email with the same user's email on resend."""
        user_id, email = await _create_pending_admin(client, admin_headers)

        with patch("app.services.admin_service.send_invite_email") as mock_send:
            await client.patch(
                RESEND_INVITE_URL.format(user_id=user_id), headers=admin_headers
            )

        mock_send.assert_called_once()
        assert mock_send.call_args[0][0] == email

    async def test_does_not_create_duplicate_user(self, client, admin_headers):
        """Resending an invite should not create a second user row."""
        user_id, email = await _create_pending_admin(client, admin_headers)

        with patch("app.services.admin_service.send_invite_email"):
            await client.patch(
                RESEND_INVITE_URL.format(user_id=user_id), headers=admin_headers
            )

        async with db_module.AsyncSessionLocal() as session:
            result = await session.execute(select(User).where(User.email == email))
            users = result.scalars().all()

        assert len(users) == 1

    async def test_user_remains_pending(self, client, admin_headers):
        """Resending an invite should not change the user's status."""
        user_id, email = await _create_pending_admin(client, admin_headers)

        with patch("app.services.admin_service.send_invite_email"):
            await client.patch(
                RESEND_INVITE_URL.format(user_id=user_id), headers=admin_headers
            )

        async with db_module.AsyncSessionLocal() as session:
            result = await session.execute(select(User).where(User.email == email))
            user = result.scalar_one()

        assert user.status == UserStatus.PENDING_VALIDATION

    async def test_response_body_is_empty(self, client, admin_headers):
        """202 response should have no body."""
        user_id, _ = await _create_pending_admin(client, admin_headers)

        with patch("app.services.admin_service.send_invite_email"):
            response = await client.patch(
                RESEND_INVITE_URL.format(user_id=user_id), headers=admin_headers
            )

        assert response.content == b""


class TestResendInviteErrors:
    async def test_returns_404_if_user_not_found(self, client, admin_headers):
        """Should return 404 if the user id does not exist."""
        response = await client.patch(
            RESEND_INVITE_URL.format(user_id=uuid.uuid4()), headers=admin_headers
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_returns_400_if_user_already_active(self, client, admin_headers):
        """Should return 400 if the user already completed onboarding."""
        user_id, email = await _create_pending_admin(client, admin_headers)

        # Simulate the invitee having already confirmed their password recovery.
        async with db_module.AsyncSessionLocal() as session:
            result = await session.execute(select(User).where(User.email == email))
            user = result.scalar_one()
            user.status = UserStatus.ACTIVE
            await session.commit()

        response = await client.patch(
            RESEND_INVITE_URL.format(user_id=user_id), headers=admin_headers
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    async def test_does_not_send_email_if_user_already_active(
        self, client, admin_headers
    ):
        """Should not call send_invite_email if the user is not pending."""
        user_id, email = await _create_pending_admin(client, admin_headers)

        async with db_module.AsyncSessionLocal() as session:
            result = await session.execute(select(User).where(User.email == email))
            user = result.scalar_one()
            user.status = UserStatus.ACTIVE
            await session.commit()

        with patch("app.services.admin_service.send_invite_email") as mock_send:
            await client.patch(
                RESEND_INVITE_URL.format(user_id=user_id), headers=admin_headers
            )

        mock_send.assert_not_called()
