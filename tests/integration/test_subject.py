import uuid
from datetime import date, timedelta

import pytest
from fastapi import status
from jose import jwt

from app.core.security import create_access_token
from app.domain.user import UserRole

pytestmark = pytest.mark.asyncio

SUBJECTS_URL = "/api/v1/subjects"


@pytest.fixture
def manager_headers():
    token = create_access_token(uuid.uuid4(), role=UserRole.ESTABLISHMENT_MANAGER)
    return {"Authorization": f"Bearer {token}"}


def _body(**overrides):
    return {
        "dni": 12345678,
        "sex": "male",
        "name": "Juan",
        "last_name": "Perez",
        "birth_date": "2010-01-01",
        "is_rural": False,
        "is_indigenous": False,
        **overrides,
    }


async def _upload(client, headers=None, **overrides):
    return await client.post(
        SUBJECTS_URL, json=_body(**overrides), headers=headers or {}
    )


class TestSubjectAuth:
    async def test_unauthenticated_returns_401(self, client):
        """No token provided should return 401."""
        response = await _upload(client)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_malformed_token_returns_401(self, client):
        """A non-JWT string as token should return 401."""
        response = await _upload(
            client, headers={"Authorization": "Bearer token_invalido"}
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_token_signed_with_wrong_secret_returns_401(self, client):
        """A JWT signed with the wrong secret should return 401."""
        forged = jwt.encode(
            {
                "sub": str(uuid.uuid4()),
                "role": "establishment_manager",
                "type": "access",
            },
            "wrong_secret",
            algorithm="HS256",
        )
        response = await _upload(client, headers={"Authorization": f"Bearer {forged}"})
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_admin_role_returns_403(self, client):
        """A valid token with admin role should return 403."""
        token = create_access_token(uuid.uuid4(), role=UserRole.ADMIN)
        response = await _upload(client, headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == status.HTTP_403_FORBIDDEN

    async def test_professional_role_returns_403(self, client):
        """A valid token with professional role should return 403."""
        token = create_access_token(uuid.uuid4(), role=UserRole.PROFESSIONAL)
        response = await _upload(client, headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == status.HTTP_403_FORBIDDEN


class TestUploadSubject:
    async def test_valid_request_returns_201(self, client, manager_headers):
        """A well-formed request with a manager token returns 201."""
        response = await _upload(client, manager_headers)
        assert response.status_code == status.HTTP_201_CREATED

    async def test_valid_request_returns_subject_data(self, client, manager_headers):
        """Response body includes all submitted fields and a generated id."""
        response = await _upload(client, manager_headers)
        data = response.json()
        assert "id" in data
        assert data["dni"] == 12345678
        assert data["sex"] == "male"
        assert data["name"] == "Juan"
        assert data["last_name"] == "Perez"
        assert data["birth_date"] == "2010-01-01"
        assert data["is_rural"] is False
        assert data["is_indigenous"] is False

    async def test_duplicate_dni_returns_409(self, client, manager_headers):
        """Registering a second subject with the same DNI returns 409."""
        await _upload(client, manager_headers)
        response = await _upload(client, manager_headers)
        assert response.status_code == status.HTTP_409_CONFLICT

    async def test_future_birth_date_returns_422(self, client, manager_headers):
        """A birth date in the future is rejected with 422."""
        future = (date.today() + timedelta(days=1)).isoformat()
        response = await _upload(client, manager_headers, birth_date=future)
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_dni_zero_returns_422(self, client, manager_headers):
        """DNI 0 is below the minimum allowed value."""
        response = await _upload(client, manager_headers, dni=0)
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_dni_above_max_returns_422(self, client, manager_headers):
        """DNI above 99999999 exceeds the Argentine DNI range."""
        response = await _upload(client, manager_headers, dni=100000000)
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_whitespace_name_returns_422(self, client, manager_headers):
        """A name composed only of whitespace is rejected after stripping."""
        response = await _upload(client, manager_headers, name="   ")
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    @pytest.mark.parametrize(
        "field",
        ["dni", "sex", "name", "last_name", "birth_date", "is_rural", "is_indigenous"],
    )
    async def test_each_required_field_is_mandatory(
        self, client, manager_headers, field
    ):
        """Omitting any single required field returns 422."""
        body = _body()
        del body[field]
        response = await client.post(SUBJECTS_URL, json=body, headers=manager_headers)
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
