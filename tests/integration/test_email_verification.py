import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest
import pytest_asyncio
from fastapi import status

REGISTER_URL = "/api/v1/auth/register/field-worker"
VERIFY_URL = "/api/v1/auth/verify-email/confirm"
RESEND_URL = "/api/v1/auth/verify-email/resend"

_REGISTRATION_EMAIL_COUNTER = 0


def _extract_token(deeplink: str | None) -> str:
    if not deeplink:
        raise AssertionError("Verification deeplink was not captured")
    token = parse_qs(urlparse(deeplink).query).get("token", [None])[0]
    if not token:
        raise AssertionError("Verification token was not found in deeplink")
    return token


async def _get_user_by_email(email: str):
    from sqlalchemy import select

    from app.db.database import AsyncSessionLocal
    from app.models.auth.user import User

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.email == email))
        return result.scalar_one()


@pytest.fixture
def capture_verification_deeplink(monkeypatch):
    captured = {"deeplink": None}

    async def _fake(to_email, deeplink, expires_at):
        captured["deeplink"] = deeplink

    monkeypatch.setattr("app.services.auth.auth_service.send_verification_email", _fake)
    return captured


@pytest.fixture
def make_db_unverified_user():
    async def _make(email: str = "unverified@test.com"):
        from app.core.security import hash_password
        from app.db.database import AsyncSessionLocal
        from app.domain.user import UserRole, UserStatus
        from app.models.auth.user import User
        from app.models.auth.user_password import UserPassword

        async with AsyncSessionLocal() as session:
            user = User(
                name="Unverified",
                last_name="User",
                email=email,
                role=UserRole.FIELD_WORKER,
                status=UserStatus.PENDING_VALIDATION,
            )
            session.add(user)
            await session.flush()
            session.add(
                UserPassword(
                    user_id=user.id,
                    password_hashed=hash_password("correct_password"),
                )
            )
            await session.commit()
            await session.refresh(user)
            return user

    return _make


@pytest_asyncio.fixture
async def register_and_verify(client, db_establishment):
    """Registers a user and verifies their email bypassing SMTP.
    Returns the email address of the verified user."""

    async def _make():
        from app.config.settings import settings
        from app.core.security import create_email_verification_token
        from app.db.database import AsyncSessionLocal
        from app.models.auth.email_verification_token import EmailVerificationToken

        email = f"reg_verify_{uuid.uuid4().hex[:8]}@example.com"
        body = {
            "email": email,
            "password": "securepass123",
            "name": "Verified",
            "last_name": "User",
            "establishments": [str(db_establishment.id)],
        }
        response = await client.post(REGISTER_URL, json=body)
        user_id = uuid.UUID(response.json()["id"])

        token, token_hash = create_email_verification_token()
        async with AsyncSessionLocal() as session:
            session.add(
                EmailVerificationToken(
                    user_id=user_id,
                    token_hash=token_hash,
                    expires_at=datetime.now(timezone.utc)
                    + timedelta(
                        minutes=settings.email_verification_token_expire_minutes
                    ),
                )
            )
            await session.commit()

        await client.post(VERIFY_URL, json={"token": token})
        return email

    return _make


@pytest_asyncio.fixture
async def registered_user(client, db_establishment, capture_verification_deeplink):
    """Registers a fresh user and returns (email, token)."""
    global _REGISTRATION_EMAIL_COUNTER
    _REGISTRATION_EMAIL_COUNTER += 1
    email = f"field_worker_{_REGISTRATION_EMAIL_COUNTER}@example.com"
    body = {
        "email": email,
        "password": "securepass123",
        "name": "Juan",
        "last_name": "Perez",
        "establishments": [str(db_establishment.id)],
    }
    await client.post(REGISTER_URL, json=body)
    token = _extract_token(capture_verification_deeplink["deeplink"])
    return email, token


@pytest_asyncio.fixture
async def unverified_user_with_token(
    client, make_db_unverified_user, capture_verification_deeplink
):
    """Creates an unverified DB user, sends a resend request,
    and returns (user, token)."""
    email = f"unverified_{uuid.uuid4().hex[:8]}@test.com"
    user = await make_db_unverified_user(email=email)
    await client.post(RESEND_URL, json={"email": user.email})
    token = _extract_token(capture_verification_deeplink["deeplink"])
    return user, token


class TestRegistrationSendsVerificationEmail:
    async def test_registration_returns_201(
        self, client, db_establishment, capture_verification_deeplink
    ):
        global _REGISTRATION_EMAIL_COUNTER
        _REGISTRATION_EMAIL_COUNTER += 1
        response = await client.post(
            REGISTER_URL,
            json={
                "email": f"field_worker_{_REGISTRATION_EMAIL_COUNTER}@example.com",
                "password": "securepass123",
                "name": "Juan",
                "last_name": "Perez",
                "establishments": [str(db_establishment.id)],
            },
        )
        assert response.status_code == status.HTTP_201_CREATED

    async def test_registration_creates_user_unverified(
        self, registered_user, client, db_establishment
    ):
        _, _ = registered_user
        # Re-register a fresh user to check the response body
        global _REGISTRATION_EMAIL_COUNTER
        _REGISTRATION_EMAIL_COUNTER += 1
        response = await client.post(
            REGISTER_URL,
            json={
                "email": f"status_check_{_REGISTRATION_EMAIL_COUNTER}@example.com",
                "password": "securepass123",
                "name": "Juan",
                "last_name": "Perez",
                "establishments": [str(db_establishment.id)],
            },
        )
        assert response.json()["status"] == "pending_validation"

    async def test_registration_triggers_verification_email(
        self, registered_user, capture_verification_deeplink
    ):
        assert capture_verification_deeplink["deeplink"] is not None

    async def test_deeplink_contains_token(self, registered_user):
        _, token = registered_user
        assert token  # _extract_token already asserts structure

    async def test_smtp_failure_still_returns_201(
        self, client, db_establishment, monkeypatch
    ):
        async def _failing_send(*args, **kwargs):
            raise TimeoutError("smtp timeout")

        monkeypatch.setattr("app.services.email_service.settings.smtp_enabled", True)
        monkeypatch.setattr("app.services.email_service.aiosmtplib.send", _failing_send)

        global _REGISTRATION_EMAIL_COUNTER
        _REGISTRATION_EMAIL_COUNTER += 1
        response = await client.post(
            REGISTER_URL,
            json={
                "email": f"smtp_fail_{_REGISTRATION_EMAIL_COUNTER}@example.com",
                "password": "securepass123",
                "name": "Juan",
                "last_name": "Perez",
                "establishments": [str(db_establishment.id)],
            },
        )
        assert response.status_code == status.HTTP_201_CREATED


class TestVerifyEmail:
    async def test_valid_token_returns_204(self, client, registered_user):
        _, token = registered_user
        response = await client.post(VERIFY_URL, json={"token": token})
        assert response.status_code == status.HTTP_204_NO_CONTENT

    async def test_valid_token_marks_email_verified(self, client, registered_user):
        email, token = registered_user
        await client.post(VERIFY_URL, json={"token": token})

        user = await _get_user_by_email(email)
        assert user.is_email_verified is True

    async def test_invalid_token_returns_401(self, client):
        response = await client.post(VERIFY_URL, json={"token": "not-a-valid-token"})
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_token_cannot_be_reused(self, client, registered_user):
        _, token = registered_user
        await client.post(VERIFY_URL, json={"token": token})
        response = await client.post(VERIFY_URL, json={"token": token})
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_missing_token_returns_422(self, client):
        response = await client.post(VERIFY_URL, json={})
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_empty_token_returns_422(self, client):
        response = await client.post(VERIFY_URL, json={"token": ""})
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


class TestResendVerificationEmail:
    async def test_resend_for_unverified_user_returns_202(
        self, client, make_db_unverified_user, capture_verification_deeplink
    ):
        user = await make_db_unverified_user()
        response = await client.post(RESEND_URL, json={"email": user.email})
        assert response.status_code == status.HTTP_202_ACCEPTED

    async def test_resend_sends_new_deeplink(self, unverified_user_with_token):
        _, token = unverified_user_with_token
        assert token  # fixture already asserts deeplink was set

    async def test_new_token_works_after_resend(
        self, client, unverified_user_with_token
    ):
        _, token = unverified_user_with_token
        response = await client.post(VERIFY_URL, json={"token": token})
        assert response.status_code == status.HTTP_204_NO_CONTENT

    async def test_old_token_revoked_after_resend(
        self, client, unverified_user_with_token, capture_verification_deeplink
    ):
        user, first_token = unverified_user_with_token

        await client.post(RESEND_URL, json={"email": user.email})
        # first_token is now revoked
        response = await client.post(VERIFY_URL, json={"token": first_token})
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_old_tokens_invalidated_after_multiple_resends(
        self, client, unverified_user_with_token, capture_verification_deeplink
    ):
        user, first_token = unverified_user_with_token

        await client.post(RESEND_URL, json={"email": user.email})
        second_token = _extract_token(capture_verification_deeplink["deeplink"])

        await client.post(RESEND_URL, json={"email": user.email})

        for old_token in (first_token, second_token):
            resp = await client.post(VERIFY_URL, json={"token": old_token})
            assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_resend_for_verified_user_returns_202(
        self, client, register_and_verify, capture_verification_deeplink
    ):
        email = await register_and_verify()
        response = await client.post(RESEND_URL, json={"email": email})
        assert response.status_code == status.HTTP_202_ACCEPTED

    async def test_verified_user_does_not_get_new_token(
        self, client, register_and_verify, capture_verification_deeplink
    ):
        email = await register_and_verify()
        capture_verification_deeplink["deeplink"] = None

        await client.post(RESEND_URL, json={"email": email})
        assert capture_verification_deeplink["deeplink"] is None

    async def test_unknown_email_returns_404(self, client):
        response = await client.post(RESEND_URL, json={"email": "ghost@example.com"})
        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_missing_email_returns_422(self, client):
        response = await client.post(RESEND_URL, json={})
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
