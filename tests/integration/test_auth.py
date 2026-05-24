import uuid

import pytest
import pytest_asyncio
from fastapi import status

from app.core.security import hash_password
from app.domain.user import UserRole, UserStatus
from app.models.user import User
from app.models.user_password import UserPassword

pytestmark = pytest.mark.asyncio

LOGIN_URL = "/api/v1/auth/login"
REGISTER_URL = "/api/v1/auth/register/establishment-manager"


@pytest_asyncio.fixture()
async def db_active_user(db_establishment):
    """Insert an active ADMIN user with a valid password record."""
    from app.db.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        user = User(
            name="Ana",
            last_name="Gomez",
            email="ana@test.com",
            role=UserRole.ADMIN,
            status=UserStatus.ACTIVE,
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


class TestRegisterManager:
    async def _register(self, client, **overrides):
        body = {
            "email": "manager@example.com",
            "password": "securepass123",
            "name": "Juan",
            "last_name": "Perez",
            "establishments": [str(uuid.uuid4())],
            **overrides,
        }
        return await client.post(REGISTER_URL, json=body)

    async def test_valid_registration_returns_201(self, client, db_establishment):
        """A well-formed request with an existing establishment returns 201."""
        response = await self._register(
            client, establishments=[str(db_establishment.id)]
        )
        assert response.status_code == status.HTTP_201_CREATED

    async def test_valid_registration_returns_user_data(self, client, db_establishment):
        """Response body includes the new user's fields and correct
        role/status defaults."""
        response = await self._register(
            client, establishments=[str(db_establishment.id)]
        )
        data = response.json()
        assert data["email"] == "manager@example.com"
        assert data["name"] == "Juan"
        assert data["last_name"] == "Perez"
        assert data["role"] == "establishment_manager"
        assert data["status"] == "pending_validation"

    async def test_duplicate_email_returns_409(self, client, db_establishment):
        """Registering with an already-used email returns 409 Conflict."""
        await self._register(client, establishments=[str(db_establishment.id)])
        response = await self._register(
            client, establishments=[str(db_establishment.id)]
        )
        assert response.status_code == status.HTTP_409_CONFLICT

    async def test_nonexistent_establishment_returns_404(self, client):
        """Referencing an establishment ID that does not exist returns 404."""
        response = await self._register(client, establishments=[str(uuid.uuid4())])
        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_empty_establishments_returns_422(self, client):
        """Sending an empty establishments list fails schema validation."""
        response = await self._register(client, establishments=[])
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_short_password_returns_422(self, client):
        """A password shorter than 8 characters fails schema validation."""
        response = await self._register(client, password="short")
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


class TestLogin:
    def _payload(self, email: str, password: str) -> dict:
        return {"email": email, "password": password, "device_id": str(uuid.uuid4())}

    async def test_valid_credentials_returns_200(self, client, db_active_user):
        response = await client.post(
            LOGIN_URL, json=self._payload("ana@test.com", "correct_password")
        )
        assert response.status_code == status.HTTP_200_OK

    async def test_response_contains_access_token(self, client, db_active_user):
        response = await client.post(
            LOGIN_URL, json=self._payload("ana@test.com", "correct_password")
        )
        assert response.json()["access_token"]

    async def test_response_contains_refresh_token(self, client, db_active_user):
        response = await client.post(
            LOGIN_URL, json=self._payload("ana@test.com", "correct_password")
        )
        assert response.json()["refresh_token"]

    async def test_response_contains_user_fields(self, client, db_active_user):
        response = await client.post(
            LOGIN_URL, json=self._payload("ana@test.com", "correct_password")
        )
        user = response.json()["user"]
        assert user["email"] == "ana@test.com"
        assert user["name"] == "Ana"
        assert user["last_name"] == "Gomez"
        assert user["role"] == UserRole.ADMIN.value

    async def test_unknown_email_returns_401(self, client):
        response = await client.post(
            LOGIN_URL, json=self._payload("nobody@test.com", "any_password")
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_wrong_password_returns_401(self, client, db_active_user):
        response = await client.post(
            LOGIN_URL, json=self._payload("ana@test.com", "wrong_password")
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_unknown_email_and_wrong_password_same_detail(
        self, client, db_active_user
    ):
        """CA 5 — ambos fallos deben devolver el mismo mensaje."""
        r_unknown = await client.post(
            LOGIN_URL, json=self._payload("ghost@test.com", "any")
        )
        r_wrong = await client.post(
            LOGIN_URL, json=self._payload("ana@test.com", "wrong_password")
        )
        assert r_unknown.json()["detail"] == r_wrong.json()["detail"]

    async def test_missing_email_returns_422(self, client):
        response = await client.post(
            LOGIN_URL,
            json={"password": "pass", "device_id": str(uuid.uuid4())},
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    async def test_invalid_email_format_returns_422(self, client):
        response = await client.post(
            LOGIN_URL,
            json={
                "email": "not-an-email",
                "password": "pass",
                "device_id": str(uuid.uuid4()),
            },
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    async def test_missing_device_id_returns_422(self, client):
        response = await client.post(
            LOGIN_URL,
            json={"email": "ana@test.com", "password": "pass"},
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


@pytest_asyncio.fixture()
async def db_pending_user():
    """Insert a PENDING_VALIDATION user with a valid password record."""
    from app.db.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        user = User(
            name="Pedro",
            last_name="Pending",
            email="pending@test.com",
            role=UserRole.ESTABLISHMENT_MANAGER,
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


class TestLoginPendingValidation:
    def _payload(self, password: str = "correct_password") -> dict:
        return {
            "email": "pending@test.com",
            "password": password,
            "device_id": str(uuid.uuid4()),
        }

    async def test_pending_user_returns_403(self, client, db_pending_user):
        response = await client.post(LOGIN_URL, json=self._payload())

        assert response.status_code == status.HTTP_403_FORBIDDEN

    async def test_pending_user_message_mentions_admin(self, client, db_pending_user):
        response = await client.post(LOGIN_URL, json=self._payload())
        detail = response.json()["detail"]

        assert "administrator" in detail

    async def test_pending_user_does_not_receive_tokens(self, client, db_pending_user):
        response = await client.post(LOGIN_URL, json=self._payload())

        assert "access_token" not in response.json()
        assert "refresh_token" not in response.json()

    async def test_pending_differs_from_invalid_credentials(
        self, client, db_pending_user
    ):
        r_pending = await client.post(LOGIN_URL, json=self._payload())
        r_invalid = await client.post(
            LOGIN_URL,
            json={
                "email": "pending@test.com",
                "password": "wrong",
                "device_id": str(uuid.uuid4()),
            },
        )

        assert r_pending.status_code == status.HTTP_403_FORBIDDEN
        assert r_invalid.status_code == status.HTTP_401_UNAUTHORIZED


LOGOUT_URL = "/api/v1/auth/logout"


@pytest_asyncio.fixture()
async def db_logged_in_user(db_active_user, client):
    """Login db_active_user and return (user, refresh_token, device_id)."""
    device_id = str(uuid.uuid4())
    response = await client.post(
        LOGIN_URL,
        json={
            "email": "ana@test.com",
            "password": "correct_password",
            "device_id": device_id,
        },
    )
    refresh_token = response.json()["refresh_token"]
    return db_active_user, refresh_token, device_id


class TestLogout:
    def _payload(self, refresh_token: str, device_id: str) -> dict:
        return {"refresh_token": refresh_token, "device_id": device_id}

    async def test_valid_logout_returns_204(self, client, db_logged_in_user):
        _, refresh_token, device_id = db_logged_in_user
        response = await client.post(
            LOGOUT_URL, json=self._payload(refresh_token, device_id)
        )
        assert response.status_code == status.HTTP_204_NO_CONTENT

    async def test_logout_response_has_no_body(self, client, db_logged_in_user):
        _, refresh_token, device_id = db_logged_in_user
        response = await client.post(
            LOGOUT_URL, json=self._payload(refresh_token, device_id)
        )
        assert response.content == b""

    async def test_token_revoked_second_logout_returns_401(
        self, client, db_logged_in_user
    ):
        """Using the same refresh token twice must fail on the second attempt."""
        _, refresh_token, device_id = db_logged_in_user
        await client.post(LOGOUT_URL, json=self._payload(refresh_token, device_id))
        response = await client.post(
            LOGOUT_URL, json=self._payload(refresh_token, device_id)
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_invalid_token_returns_401(self, client, db_active_user):
        response = await client.post(
            LOGOUT_URL,
            json=self._payload("invalid-token", str(uuid.uuid4())),
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_wrong_device_id_returns_401(self, client, db_logged_in_user):
        """Valid token but wrong device_id must be rejected."""
        _, refresh_token, _ = db_logged_in_user
        response = await client.post(
            LOGOUT_URL,
            json=self._payload(refresh_token, str(uuid.uuid4())),
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_missing_refresh_token_returns_422(self, client, db_active_user):
        response = await client.post(
            LOGOUT_URL,
            json={"device_id": str(uuid.uuid4())},
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_missing_device_id_returns_422(self, client, db_active_user):
        response = await client.post(
            LOGOUT_URL,
            json={"refresh_token": "some-token"},
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
