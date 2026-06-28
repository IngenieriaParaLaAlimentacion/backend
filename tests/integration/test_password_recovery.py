import uuid
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import status

pytestmark = pytest.mark.asyncio

REQUEST_URL = "/api/v1/auth/password-recovery/request"
CONFIRM_URL = "/api/v1/auth/password-recovery/confirm"
LOGIN_URL = "/api/v1/auth/login"
LOGOUT_URL = "/api/v1/auth/logout"


def _extract_token(deeplink: str | None) -> str:
    if not deeplink:
        raise AssertionError("Password recovery deeplink was not captured")
    token = parse_qs(urlparse(deeplink).query).get("token", [None])[0]
    if not token:
        raise AssertionError("Password recovery token was not found in deeplink")
    return token


def _login_payload(email: str, password: str) -> dict:
    return {"email": email, "password": password, "device_id": str(uuid.uuid4())}


@pytest.fixture
def capture_deeplink(monkeypatch):
    """Intercepts send_recovery_email and returns a dict with the captured deeplink."""
    captured = {"deeplink": None}

    async def _fake(to_email, deeplink, expires_at):
        captured["deeplink"] = deeplink

    monkeypatch.setattr("app.services.auth_service.send_recovery_email", _fake)
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

    async def test_smtp_failure_still_returns_202(
        self, client, db_active_user, monkeypatch
    ):
        async def _failing_send(*args, **kwargs):
            raise TimeoutError("smtp timeout")

        monkeypatch.setattr("app.services.email_service.settings.smtp_enabled", True)
        monkeypatch.setattr("app.services.email_service.aiosmtplib.send", _failing_send)

        response = await client.post(REQUEST_URL, json={"email": "ana@test.com"})
        assert response.status_code == status.HTTP_202_ACCEPTED

    async def test_second_request_revokes_previous_token(
        self, client, db_active_user, capture_deeplink
    ):
        await client.post(REQUEST_URL, json={"email": "ana@test.com"})
        first_token = _extract_token(capture_deeplink["deeplink"])

        await client.post(REQUEST_URL, json={"email": "ana@test.com"})

        confirm = await client.post(
            CONFIRM_URL, json={"token": first_token, "new_password": "newpassword123"}
        )
        assert confirm.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_missing_email_returns_422(self, client):
        response = await client.post(REQUEST_URL, json={})
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


class TestPasswordRecoveryConfirm:
    async def test_invalid_token_returns_401(self, client):
        response = await client.post(
            CONFIRM_URL,
            json={"token": "not-a-valid-token", "new_password": "newpassword123"},
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

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

    async def test_token_cannot_be_reused(
        self, client, db_active_user, capture_deeplink
    ):
        await client.post(REQUEST_URL, json={"email": "ana@test.com"})
        token = _extract_token(capture_deeplink["deeplink"])

        await client.post(
            CONFIRM_URL, json={"token": token, "new_password": "newpassword123"}
        )
        response = await client.post(
            CONFIRM_URL, json={"token": token, "new_password": "anotherpassword123"}
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
