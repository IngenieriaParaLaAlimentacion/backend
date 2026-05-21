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
APPROVE_URL = "/api/v1/admin/managers/{user_id}/approve"


async def _make_list_request(client, *, headers=None):
    return await client.get(ADMIN_USERS_URL, headers=headers or {})


async def _make_approve_request(client, *, headers=None):
    return await client.post(
        APPROVE_URL.format(user_id=uuid.uuid4()),
        json={"approved_establishment_ids": [str(uuid.uuid4())]},
        headers=headers or {},
    )


@pytest.fixture(
    params=[
        pytest.param(_make_list_request, id="GET /admin/users"),
        pytest.param(_make_approve_request, id="POST /admin/managers/{id}/approve"),
    ]
)
def any_admin_request(request):
    return request.param


@pytest.fixture
def admin_headers():
    token = create_access_token(uuid.uuid4(), role=UserRole.ADMIN)
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def db_establishment_2(app):
    """Insert a second Establishment row and return the ORM instance."""
    from app.db.database import AsyncSessionLocal
    from app.models.establishment import Establishment

    async with AsyncSessionLocal() as session:
        establishment = Establishment(name="Centro B", address="Calle B 456")
        session.add(establishment)
        await session.commit()
        await session.refresh(establishment)
        return establishment


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


class TestAdminAuth:
    async def test_unauthenticated(self, client, any_admin_request):
        """Should return 401 if no access token is provided."""
        response = await any_admin_request(client)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_malformed_token(self, client, any_admin_request):
        """Should return 401 if the token is not a valid JWT."""
        response = await any_admin_request(
            client, headers={"Authorization": "Bearer token_invalido"}
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_token_signed_with_wrong_secret(self, client, any_admin_request):
        """Should return 401 if the token is signed with the wrong secret."""
        payload = {"sub": str(uuid.uuid4()), "role": "admin", "type": "access"}
        forged_token = jwt.encode(payload, "secret_manager", algorithm="HS256")
        response = await any_admin_request(
            client, headers={"Authorization": f"Bearer {forged_token}"}
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_manager_is_forbidden(self, client, any_admin_request):
        """Should return 403 when a valid manager token is provided."""
        token = create_access_token(uuid.uuid4(), role=UserRole.ESTABLISHMENT_MANAGER)
        response = await any_admin_request(
            client, headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    async def test_professional_is_forbidden(self, client, any_admin_request):
        """Should return 403 when a valid professional token is provided."""
        token = create_access_token(uuid.uuid4(), role=UserRole.PROFESSIONAL)
        response = await any_admin_request(
            client, headers={"Authorization": f"Bearer {token}"}
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


class TestApproveManager:
    async def test_response_has_required_fields(
        self, client, admin_headers, registered_manager, db_establishment
    ):
        """Should return user fields and establishments with their status."""
        url = APPROVE_URL.format(user_id=registered_manager["id"])
        response = await client.post(
            url,
            json={"approved_establishment_ids": [str(db_establishment.id)]},
            headers=admin_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert "id" in body
        assert "email" in body
        assert "name" in body
        assert "last_name" in body
        assert "role" in body
        assert "status" in body
        assert "establishments" in body
        for estab in body["establishments"]:
            assert "id" in estab
            assert "name" in estab
            assert "address" in estab
            assert "status" in estab

    async def test_approved_establishment_has_approved_status(
        self, client, admin_headers, registered_manager, db_establishment
    ):
        """Establishments in the request body should have status approved."""
        url = APPROVE_URL.format(user_id=registered_manager["id"])
        response = await client.post(
            url,
            json={"approved_establishment_ids": [str(db_establishment.id)]},
            headers=admin_headers,
        )

        body = response.json()
        assert body["establishments"][0]["status"] == "approved"

    async def test_user_status_becomes_active(
        self, client, admin_headers, registered_manager, db_establishment
    ):
        """Manager status should be active after approval."""
        url = APPROVE_URL.format(user_id=registered_manager["id"])
        response = await client.post(
            url,
            json={"approved_establishment_ids": [str(db_establishment.id)]},
            headers=admin_headers,
        )

        assert response.json()["status"] == UserStatus.ACTIVE.value

    async def test_partial_approval_annotates_statuses_correctly(
        self, client, admin_headers, db_establishment, db_establishment_2
    ):
        """Approved establishments get approved, the rest get rejected."""
        response = await client.post(
            REGISTER_MANAGER_URL,
            json={
                "email": f"manager_{uuid.uuid4().hex[:6]}@test.com",
                "password": "Password123!",
                "name": "Test",
                "last_name": "Manager",
                "establishments": [
                    str(db_establishment.id),
                    str(db_establishment_2.id),
                ],
            },
        )
        assert response.status_code == status.HTTP_201_CREATED
        manager_id = response.json()["id"]

        url = APPROVE_URL.format(user_id=manager_id)
        response = await client.post(
            url,
            json={"approved_establishment_ids": [str(db_establishment.id)]},
            headers=admin_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        establishments = response.json()["establishments"]
        statuses = {e["id"]: e["status"] for e in establishments}
        assert statuses[str(db_establishment.id)] == "approved"
        assert statuses[str(db_establishment_2.id)] == "rejected"

    async def test_idempotent_when_called_twice(
        self, client, admin_headers, registered_manager, db_establishment
    ):
        """Calling approve twice should return 200 both times."""
        url = APPROVE_URL.format(user_id=registered_manager["id"])
        body = {"approved_establishment_ids": [str(db_establishment.id)]}

        first = await client.post(url, json=body, headers=admin_headers)
        second = await client.post(url, json=body, headers=admin_headers)

        assert first.status_code == status.HTTP_200_OK
        assert second.status_code == status.HTTP_200_OK

    async def test_user_not_found(self, client, admin_headers):
        """Should return 404 if the manager does not exist."""
        url = APPROVE_URL.format(user_id=uuid.uuid4())
        response = await client.post(
            url,
            json={"approved_establishment_ids": [str(uuid.uuid4())]},
            headers=admin_headers,
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_establishment_not_associated_with_manager(
        self, client, admin_headers, registered_manager
    ):
        """Should return 404 if an establishment ID is not linked to this manager."""
        url = APPROVE_URL.format(user_id=registered_manager["id"])
        response = await client.post(
            url,
            json={"approved_establishment_ids": [str(uuid.uuid4())]},
            headers=admin_headers,
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_empty_approved_ids_rejected(
        self, client, admin_headers, registered_manager
    ):
        """Should return 422 if approved_establishment_ids is empty."""
        url = APPROVE_URL.format(user_id=registered_manager["id"])
        response = await client.post(
            url,
            json={"approved_establishment_ids": []},
            headers=admin_headers,
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
