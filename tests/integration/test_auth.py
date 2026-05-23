import uuid

import pytest
from fastapi import status

pytestmark = pytest.mark.asyncio


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
        return await client.post(
            "/api/v1/auth/register/establishment-manager", json=body
        )

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
