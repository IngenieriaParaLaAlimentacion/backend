import uuid

import pytest
import pytest_asyncio
from fastapi import status

from app.domain.user import UserRole

pytestmark = pytest.mark.asyncio

LOGIN_URL = "/api/v1/auth/login"
LOGOUT_URL = "/api/v1/auth/logout"
REFRESH_URL = "/api/v1/auth/refresh"
REGISTER_URL = "/api/v1/auth/register/field-worker"


@pytest_asyncio.fixture()
async def db_logged_in_for_refresh(db_logged_in_user):
    return db_logged_in_user


class TestRegisterFieldWorker:
    async def _register(self, client, **overrides):
        body = {
            "email": "field_worker@example.com",
            "password": "securepass123",
            "name": "Juan",
            "last_name": "Perez",
            "establishments": [str(uuid.uuid4())],
            **overrides,
        }
        return await client.post(REGISTER_URL, json=body)

    async def test_valid_registration_returns_201(self, client, db_establishment):
        response = await self._register(
            client, establishments=[str(db_establishment.id)]
        )
        assert response.status_code == status.HTTP_201_CREATED

    async def test_valid_registration_returns_user_data(self, client, db_establishment):
        response = await self._register(
            client, establishments=[str(db_establishment.id)]
        )
        data = response.json()
        assert data["email"] == "field_worker@example.com"
        assert data["name"] == "Juan"
        assert data["last_name"] == "Perez"
        assert data["role"] == "field_worker"
        assert data["status"] == "pending_validation"

    async def test_duplicate_email_returns_409(self, client, db_establishment):
        await self._register(client, establishments=[str(db_establishment.id)])
        response = await self._register(
            client, establishments=[str(db_establishment.id)]
        )
        assert response.status_code == status.HTTP_409_CONFLICT

    async def test_nonexistent_establishment_returns_404(self, client):
        response = await self._register(client, establishments=[str(uuid.uuid4())])
        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_empty_establishments_returns_422(self, client):
        response = await self._register(client, establishments=[])
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_short_password_returns_422(self, client):
        response = await self._register(client, password="short")
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_optional_fields_are_returned_in_response(
        self, client, db_establishment
    ):
        response = await self._register(
            client,
            establishments=[str(db_establishment.id)],
            locality="Villa Lugano",
            description="Community health promoter",
            contact_phone="1134567890",
        )
        data = response.json()
        assert data["locality"] == "Villa Lugano"
        assert data["description"] == "Community health promoter"
        assert data["contact_phone"] == "1134567890"

    async def test_optional_fields_default_to_null(self, client, db_establishment):
        response = await self._register(
            client, establishments=[str(db_establishment.id)]
        )
        data = response.json()
        assert data["locality"] is None
        assert data["description"] is None
        assert data["contact_phone"] is None

    async def test_invalid_phone_format_returns_422(self, client, db_establishment):
        response = await self._register(
            client,
            establishments=[str(db_establishment.id)],
            contact_phone="not-a-phone!!",
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_description_exceeding_max_length_returns_422(
        self, client, db_establishment
    ):
        response = await self._register(
            client,
            establishments=[str(db_establishment.id)],
            description="x" * 501,
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_locality_exceeding_max_length_returns_422(
        self, client, db_establishment
    ):
        response = await self._register(
            client,
            establishments=[str(db_establishment.id)],
            locality="x" * 101,
        )
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
        r_unknown = await client.post(
            LOGIN_URL, json=self._payload("ghost@test.com", "any")
        )
        r_wrong = await client.post(
            LOGIN_URL, json=self._payload("ana@test.com", "wrong_password")
        )
        assert r_unknown.json()["detail"] == r_wrong.json()["detail"]

    async def test_missing_email_returns_422(self, client):
        response = await client.post(
            LOGIN_URL, json={"password": "pass", "device_id": str(uuid.uuid4())}
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_invalid_email_format_returns_422(self, client):
        response = await client.post(
            LOGIN_URL,
            json={
                "email": "not-an-email",
                "password": "pass",
                "device_id": str(uuid.uuid4()),
            },
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_missing_device_id_returns_422(self, client):
        response = await client.post(
            LOGIN_URL, json={"email": "ana@test.com", "password": "pass"}
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


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
        assert "administrator" in response.json()["detail"]

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
        _, refresh_token, device_id = db_logged_in_user
        await client.post(LOGOUT_URL, json=self._payload(refresh_token, device_id))
        response = await client.post(
            LOGOUT_URL, json=self._payload(refresh_token, device_id)
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_invalid_token_returns_401(self, client, db_active_user):
        response = await client.post(
            LOGOUT_URL, json=self._payload("invalid-token", str(uuid.uuid4()))
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_wrong_device_id_returns_401(self, client, db_logged_in_user):
        _, refresh_token, _ = db_logged_in_user
        response = await client.post(
            LOGOUT_URL, json=self._payload(refresh_token, str(uuid.uuid4()))
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_missing_refresh_token_returns_422(self, client, db_active_user):
        response = await client.post(LOGOUT_URL, json={"device_id": str(uuid.uuid4())})
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_missing_device_id_returns_422(self, client, db_active_user):
        response = await client.post(LOGOUT_URL, json={"refresh_token": "some-token"})
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


class TestRefreshSuccess:
    def _payload(self, refresh_token: str, device_id: str) -> dict:
        return {"refresh_token": refresh_token, "device_id": device_id}

    async def test_valid_refresh_returns_200(self, client, db_logged_in_for_refresh):
        _, refresh_token, device_id = db_logged_in_for_refresh
        response = await client.post(
            REFRESH_URL, json=self._payload(refresh_token, device_id)
        )
        assert response.status_code == status.HTTP_200_OK

    async def test_response_contains_access_token(
        self, client, db_logged_in_for_refresh
    ):
        _, refresh_token, device_id = db_logged_in_for_refresh
        response = await client.post(
            REFRESH_URL, json=self._payload(refresh_token, device_id)
        )
        assert response.json()["access_token"]

    async def test_response_contains_refresh_token(
        self, client, db_logged_in_for_refresh
    ):
        _, refresh_token, device_id = db_logged_in_for_refresh
        response = await client.post(
            REFRESH_URL, json=self._payload(refresh_token, device_id)
        )
        assert response.json()["refresh_token"]

    async def test_new_refresh_token_differs_from_old(
        self, client, db_logged_in_for_refresh
    ):
        _, refresh_token, device_id = db_logged_in_for_refresh
        response = await client.post(
            REFRESH_URL, json=self._payload(refresh_token, device_id)
        )
        assert response.json()["refresh_token"] != refresh_token

    async def test_new_refresh_token_is_usable(self, client, db_logged_in_for_refresh):
        _, refresh_token, device_id = db_logged_in_for_refresh
        first = await client.post(
            REFRESH_URL, json=self._payload(refresh_token, device_id)
        )
        second = await client.post(
            REFRESH_URL, json=self._payload(first.json()["refresh_token"], device_id)
        )
        assert second.status_code == status.HTTP_200_OK

    async def test_new_refresh_token_can_logout(self, client, db_logged_in_for_refresh):
        _, refresh_token, device_id = db_logged_in_for_refresh
        first = await client.post(
            REFRESH_URL, json=self._payload(refresh_token, device_id)
        )
        response = await client.post(
            LOGOUT_URL, json=self._payload(first.json()["refresh_token"], device_id)
        )
        assert response.status_code == status.HTTP_204_NO_CONTENT


class TestRefreshInvalidToken:
    def _payload(self, refresh_token: str, device_id: str) -> dict:
        return {"refresh_token": refresh_token, "device_id": device_id}

    async def test_invalid_token_returns_401(self, client, db_active_user):
        response = await client.post(
            REFRESH_URL,
            json=self._payload("completely-invalid-token", str(uuid.uuid4())),
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_wrong_device_id_returns_401(self, client, db_logged_in_for_refresh):
        _, refresh_token, _ = db_logged_in_for_refresh
        response = await client.post(
            REFRESH_URL, json=self._payload(refresh_token, str(uuid.uuid4()))
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_old_token_rejected_after_rotation(
        self, client, db_logged_in_for_refresh
    ):
        _, refresh_token, device_id = db_logged_in_for_refresh
        await client.post(REFRESH_URL, json=self._payload(refresh_token, device_id))
        response = await client.post(
            REFRESH_URL, json=self._payload(refresh_token, device_id)
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_logged_out_token_cannot_be_refreshed(
        self, client, db_logged_in_for_refresh
    ):
        _, refresh_token, device_id = db_logged_in_for_refresh
        await client.post(LOGOUT_URL, json=self._payload(refresh_token, device_id))
        response = await client.post(
            REFRESH_URL, json=self._payload(refresh_token, device_id)
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestRefreshValidation:
    async def test_missing_refresh_token_returns_422(self, client, db_active_user):
        response = await client.post(REFRESH_URL, json={"device_id": str(uuid.uuid4())})
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_missing_device_id_returns_422(self, client, db_active_user):
        response = await client.post(REFRESH_URL, json={"refresh_token": "some-token"})
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_empty_body_returns_422(self, client, db_active_user):
        response = await client.post(REFRESH_URL, json={})
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
