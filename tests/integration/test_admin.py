import uuid

import pytest
import pytest_asyncio
from fastapi import status
from jose import jwt

from app.core.security import create_access_token
from app.domain.user import UserRole, UserStatus

pytestmark = pytest.mark.asyncio

ADMIN_USERS_URL = "/api/v1/admin/users"
REGISTER_MANAGER_URL = "/api/v1/auth/register/establishment-manager"


@pytest.fixture
def admin_headers():
    token = create_access_token(uuid.uuid4(), role=UserRole.ADMIN)
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def registered_manager(client, db_establishment):
    """Register a manager linked to the test establishment and return the response
    body."""
    response = await client.post(
        REGISTER_MANAGER_URL,
        json={
            "email": f"manager_{uuid.uuid4().hex[:6]}@test.com",
            "password": "Password123!",
            "name": "Test",
            "last_name": "Manager",
            "establishments": [str(db_establishment.id)],
        },
    )
    assert response.status_code == status.HTTP_201_CREATED
    return response.json()


class TestListUsersAuth:
    async def test_unauthenticated(self, client):
        """Should return 401 if no access token is provided."""
        response = await client.get(ADMIN_USERS_URL)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_malformed_token(self, client):
        """Should return 401 if the access token is not a valid JWT."""
        response = await client.get(
            ADMIN_USERS_URL,
            headers={"Authorization": "Bearer token_invalido"},
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_token_signed_with_wrong_secret(self, client):
        """Should return 401 if the token is signed with the wrong secret."""
        payload = {"sub": str(uuid.uuid4()), "role": "admin", "type": "access"}
        forged_token = jwt.encode(payload, "secret_manager", algorithm="HS256")

        response = await client.get(
            ADMIN_USERS_URL,
            headers={"Authorization": f"Bearer {forged_token}"},
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_admin_has_access(self, client, admin_headers):
        """Should return 200 when a valid admin token is provided."""
        response = await client.get(ADMIN_USERS_URL, headers=admin_headers)
        assert response.status_code == status.HTTP_200_OK

    async def test_manager_is_forbidden(self, client):
        """Should return 403 when a valid manager token is provided."""
        token = create_access_token(uuid.uuid4(), role=UserRole.ESTABLISHMENT_MANAGER)
        response = await client.get(
            ADMIN_USERS_URL,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    async def test_professional_is_forbidden(self, client):
        """Should return 403 when a valid professional token is provided."""
        token = create_access_token(uuid.uuid4(), role=UserRole.PROFESSIONAL)
        response = await client.get(
            ADMIN_USERS_URL,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN


class TestListUsersPagination:
    async def test_returns_paginated_structure(self, client, admin_headers):
        """Should return a response with all pagination fields."""
        response = await client.get(ADMIN_USERS_URL, headers=admin_headers)

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert "items" in body
        assert "total" in body
        assert "page" in body
        assert "page_size" in body
        assert "total_pages" in body

    async def test_default_pagination_values(self, client, admin_headers):
        """Should default to page 1 and page_size 20."""
        response = await client.get(ADMIN_USERS_URL, headers=admin_headers)

        body = response.json()
        assert body["page"] == 1
        assert body["page_size"] == 20

    async def test_custom_page_size(self, client, admin_headers):
        """Should respect a custom page_size query param."""
        response = await client.get(
            f"{ADMIN_USERS_URL}?page_size=5", headers=admin_headers
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["page_size"] == 5

    async def test_page_size_above_limit_rejected(self, client, admin_headers):
        """Should return 422 if page_size exceeds 100."""
        response = await client.get(
            f"{ADMIN_USERS_URL}?page_size=200", headers=admin_headers
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_page_zero_rejected(self, client, admin_headers):
        """Should return 422 if page is less than 1."""
        response = await client.get(f"{ADMIN_USERS_URL}?page=0", headers=admin_headers)
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_items_have_required_fields(
        self, client, admin_headers, registered_manager
    ):
        """Each item should expose id, email, name, last_name, role,
        status and establishments."""
        response = await client.get(ADMIN_USERS_URL, headers=admin_headers)

        assert response.status_code == status.HTTP_200_OK
        items = response.json()["items"]
        assert len(items) > 0
        for item in items:
            assert "id" in item
            assert "email" in item
            assert "name" in item
            assert "last_name" in item
            assert "role" in item
            assert "status" in item
            assert "establishments" in item

    async def test_filter_by_role_returns_only_matching_users(
        self, client, admin_headers, registered_manager
    ):
        """Should return only users with the requested role."""
        response = await client.get(
            f"{ADMIN_USERS_URL}?role={UserRole.ESTABLISHMENT_MANAGER.value}",
            headers=admin_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        items = response.json()["items"]
        assert all(item["role"] == UserRole.ESTABLISHMENT_MANAGER for item in items)

    async def test_filter_by_role_no_users(
        self, client, admin_headers, registered_manager
    ):
        """Should return empty when filtering by a role with no users."""
        response = await client.get(
            f"{ADMIN_USERS_URL}?role={UserRole.PROFESSIONAL.value}",
            headers=admin_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["items"] == []

    async def test_filter_by_status_returns_only_matching_users(
        self, client, admin_headers, registered_manager
    ):
        """Should return only users with the requested status."""
        response = await client.get(
            f"{ADMIN_USERS_URL}?status={UserStatus.PENDING_VALIDATION.value}",
            headers=admin_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        items = response.json()["items"]
        assert all(item["status"] == UserStatus.PENDING_VALIDATION for item in items)

    async def test_filter_by_status_no_users(
        self, client, admin_headers, registered_manager
    ):
        """Should return empty when filtering by a status with no users."""
        response = await client.get(
            f"{ADMIN_USERS_URL}?status={UserStatus.ACTIVE.value}",
            headers=admin_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["items"] == []
