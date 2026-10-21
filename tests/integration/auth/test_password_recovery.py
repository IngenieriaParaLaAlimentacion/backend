import uuid
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import status
from sqlalchemy import select

import app.db.database as db_module
from app.domain.user import UserRole, UserStatus
from app.models.auth.password_recovery_token import PasswordRecoveryToken
from app.models.auth.user import User
from tests.integration.auth.helpers import insert_user_with_recovery_token
from tests.integration.urls import LOGIN_URL, LOGOUT_URL

REQUEST_URL = "/api/v1/auth/password-recovery/request"
CONFIRM_URL = "/api/v1/auth/password-recovery/confirm"


def _extract_token(deeplink: str | None) -> str:
    if not deeplink:
        raise AssertionError("Password recovery deeplink was not captured")
    token = parse_qs(urlparse(deeplink).query).get("token", [None])[0]
    if not token:
        raise AssertionError("Password recovery token was not found in deeplink")
    return token


async def _expire_recovery_tokens() -> None:
    """Backdate every recovery token so the expiry branch is reachable."""
    from sqlalchemy import text

    from app.db.database import engine

    async with engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE password_recovery_tokens "
                "SET expires_at = now() - interval '1 hour'"
            )
        )


def _login_payload(email: str, password: str) -> dict:
    return {"email": email, "password": password, "device_id": str(uuid.uuid4())}


@pytest.fixture
def capture_deeplink(monkeypatch):
    """Intercepts send_recovery_email and returns a dict with the captured deeplink."""
    captured = {"deeplink": None}

    async def _fake(to_email, deeplink, expires_at):
        captured["deeplink"] = deeplink

    monkeypatch.setattr("app.services.auth.auth_service.send_recovery_email", _fake)
    return captured


class TestPasswordRecoveryRequest:
    async def test_unknown_email_returns_202(self, client):
        response = await client.post(REQUEST_URL, json={"email": "ghost@example.com"})
        assert response.status_code == status.HTTP_202_ACCEPTED

    async def test_known_email_returns_202(
        self, client, db_active_user, capture_deeplink
    ):
        response = await client.post(REQUEST_URL, json={"email": "ana@test.com"})
        assert response.status_code == status.HTTP_202_ACCEPTED

    async def test_known_email_triggers_email_send(
        self, client, db_active_user, capture_deeplink
    ):
        await client.post(REQUEST_URL, json={"email": "ana@test.com"})
        assert capture_deeplink["deeplink"] is not None

    async def test_deeplink_contains_token(
        self, client, db_active_user, capture_deeplink
    ):
        await client.post(REQUEST_URL, json={"email": "ana@test.com"})
        token = parse_qs(urlparse(capture_deeplink["deeplink"]).query).get("token")
        assert token and token[0]

    async def test_deeplink_uses_backoffice_origin(
        self, client, db_active_user, capture_deeplink, monkeypatch
    ):
        """Every role is sent to the backoffice origin."""
        monkeypatch.setattr(
            "app.config.settings.settings.backoffice_deeplink_base",
            "https://backoffice.example.com",
        )

        await client.post(REQUEST_URL, json={"email": "ana@test.com"})

        deeplink = capture_deeplink["deeplink"]
        assert urlparse(deeplink).netloc == "backoffice.example.com"

    async def test_smtp_failure_still_returns_202(
        self, client, db_active_user, monkeypatch
    ):
        async def _failing_send(*args, **kwargs):
            raise TimeoutError("smtp timeout")

        monkeypatch.setattr("app.services.email_service.settings.smtp_enabled", True)
        monkeypatch.setattr("app.services.email_service.aiosmtplib.send", _failing_send)

        response = await client.post(REQUEST_URL, json={"email": "ana@test.com"})
        assert response.status_code == status.HTTP_202_ACCEPTED

    async def test_missing_email_returns_422(self, client):
        response = await client.post(REQUEST_URL, json={})
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


class TestPasswordRecoveryConfirm:
    async def test_unknown_token_is_reported_generically(self, client):
        """A token that never existed must not be distinguishable from one that
        did -- that would confirm an address was issued a link."""
        response = await client.post(
            CONFIRM_URL,
            json={"token": "not-a-valid-token", "new_password": "newpassword123"},
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.json()["type"] == "/errors/auth/invalid-recovery-token"

    async def test_reused_token_is_reported_as_used(
        self, client, db_active_user, capture_deeplink
    ):
        await client.post(REQUEST_URL, json={"email": "ana@test.com"})
        token = _extract_token(capture_deeplink["deeplink"])
        await client.post(
            CONFIRM_URL, json={"token": token, "new_password": "newpassword123"}
        )

        response = await client.post(
            CONFIRM_URL, json={"token": token, "new_password": "otherpassword123"}
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.json()["type"] == "/errors/auth/recovery-token-used"

    async def test_superseded_token_is_reported_as_used(
        self, client, db_active_user, capture_deeplink
    ):
        """Requesting a second link marks the first used; the client needs to be
        told that, not just 'invalid'."""
        await client.post(REQUEST_URL, json={"email": "ana@test.com"})
        first_token = _extract_token(capture_deeplink["deeplink"])
        await client.post(REQUEST_URL, json={"email": "ana@test.com"})

        response = await client.post(
            CONFIRM_URL, json={"token": first_token, "new_password": "newpassword123"}
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.json()["type"] == "/errors/auth/recovery-token-used"

    async def test_expired_token_is_reported_as_expired(
        self, client, db_active_user, capture_deeplink
    ):
        await client.post(REQUEST_URL, json={"email": "ana@test.com"})
        token = _extract_token(capture_deeplink["deeplink"])
        await _expire_recovery_tokens()

        response = await client.post(
            CONFIRM_URL, json={"token": token, "new_password": "newpassword123"}
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.json()["type"] == "/errors/auth/recovery-token-expired"

    async def test_valid_token_returns_204(
        self, client, db_active_user, capture_deeplink
    ):
        await client.post(REQUEST_URL, json={"email": "ana@test.com"})
        token = _extract_token(capture_deeplink["deeplink"])

        response = await client.post(
            CONFIRM_URL, json={"token": token, "new_password": "newpassword123"}
        )
        assert response.status_code == status.HTTP_204_NO_CONTENT

    async def test_old_password_rejected_after_reset(
        self, client, db_active_user, capture_deeplink
    ):
        await client.post(REQUEST_URL, json={"email": "ana@test.com"})
        token = _extract_token(capture_deeplink["deeplink"])
        await client.post(
            CONFIRM_URL, json={"token": token, "new_password": "newpassword123"}
        )

        response = await client.post(
            LOGIN_URL, json=_login_payload("ana@test.com", "correct_password")
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_new_password_accepted_after_reset(
        self, client, db_active_user, capture_deeplink
    ):
        await client.post(REQUEST_URL, json={"email": "ana@test.com"})
        token = _extract_token(capture_deeplink["deeplink"])
        await client.post(
            CONFIRM_URL, json={"token": token, "new_password": "newpassword123"}
        )

        response = await client.post(
            LOGIN_URL, json=_login_payload("ana@test.com", "newpassword123")
        )
        assert response.status_code == status.HTTP_200_OK

    async def test_active_sessions_revoked_after_reset(
        self, client, db_logged_in_user, capture_deeplink
    ):
        user, refresh_token, device_id = db_logged_in_user

        await client.post(REQUEST_URL, json={"email": "ana@test.com"})
        token = _extract_token(capture_deeplink["deeplink"])
        await client.post(
            CONFIRM_URL, json={"token": token, "new_password": "newpassword123"}
        )

        response = await client.post(
            LOGOUT_URL, json={"refresh_token": refresh_token, "device_id": device_id}
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_missing_token_returns_422(self, client):
        response = await client.post(
            CONFIRM_URL, json={"new_password": "newpassword123"}
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_missing_new_password_returns_422(self, client):
        response = await client.post(CONFIRM_URL, json={"token": "sometoken"})
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


class TestDecoupledPasswordRecovery:
    async def test_pending_field_worker_resets_password_and_remains_pending(
        self, client, db_pending_user, capture_deeplink
    ):
        await client.post(REQUEST_URL, json={"email": "pending@test.com"})
        token = _extract_token(capture_deeplink["deeplink"])

        confirm_res = await client.post(
            CONFIRM_URL, json={"token": token, "new_password": "newpassword123"}
        )
        assert confirm_res.status_code == status.HTTP_204_NO_CONTENT

        async with db_module.AsyncSessionLocal() as session:
            result = await session.execute(
                select(User).where(User.email == "pending@test.com")
            )
            user = result.scalar_one()
            assert user.status == UserStatus.PENDING_VALIDATION
            assert user.is_email_verified is True

        login_res = await client.post(
            LOGIN_URL, json=_login_payload("pending@test.com", "newpassword123")
        )
        assert login_res.status_code == status.HTTP_403_FORBIDDEN
        assert login_res.json()["type"] == "/errors/account-pending-validation"


class TestPendingBackofficeBlockedFromPasswordRecovery:
    @pytest.mark.parametrize("role", [UserRole.ADMIN, UserRole.ANALYST])
    async def test_request_password_recovery_skips_email_for_pending_backoffice(
        self, client, capture_deeplink, role
    ):
        user, _ = await insert_user_with_recovery_token(role)

        res = await client.post(REQUEST_URL, json={"email": user.email})
        assert res.status_code == status.HTTP_202_ACCEPTED
        assert capture_deeplink["deeplink"] is None

    @pytest.mark.parametrize("role", [UserRole.ADMIN, UserRole.ANALYST])
    async def test_confirm_password_recovery_rejected_for_pending_backoffice(
        self, client, role
    ):
        user, token = await insert_user_with_recovery_token(role)

        res = await client.post(
            CONFIRM_URL, json={"token": token, "new_password": "newpassword123"}
        )
        assert res.status_code == status.HTTP_401_UNAUTHORIZED
        assert res.json()["type"] == "/errors/auth/invalid-recovery-token"

        # The invitee must still be able to accept the invite with the same link.
        async with db_module.AsyncSessionLocal() as session:
            recovery_token = (
                await session.execute(
                    select(PasswordRecoveryToken).where(
                        PasswordRecoveryToken.user_id == user.id
                    )
                )
            ).scalar_one()
        assert recovery_token.used is False
