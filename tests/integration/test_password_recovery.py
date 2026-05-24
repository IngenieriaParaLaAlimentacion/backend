from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import status

pytestmark = pytest.mark.asyncio

REQUEST_URL = "/api/v1/auth/password-recovery/request"
CONFIRM_URL = "/api/v1/auth/password-recovery/confirm"
LOGIN_URL = "/api/v1/auth/login"
LOGOUT_URL = "/api/v1/auth/logout"


@pytest.fixture
def capture_deeplink(monkeypatch):
    """Intercepts send_recovery_email and returns a dict with the captured deeplink."""
    captured = {"deeplink": None}

    def _fake(to_email, deeplink, expires_at):
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
        class _FailingSMTP:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                raise TimeoutError("smtp timeout")

            def __exit__(self, *args):
                return False

        monkeypatch.setattr("app.core.password_recovery.settings.smtp_enabled", True)
        monkeypatch.setattr("app.core.password_recovery.smtplib.SMTP", _FailingSMTP)

        response = await client.post(REQUEST_URL, json={"email": "ana@test.com"})
        assert response.status_code == status.HTTP_202_ACCEPTED

    async def test_missing_email_returns_422(self, client):
        response = await client.post(REQUEST_URL, json={})
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
