import uuid

import pytest
import pytest_asyncio
from fastapi import status
from jose import jwt
from sqlalchemy import select

import app.db.database as db_module
from app.core.security import create_access_token
from app.domain.user import UserRole, UserStatus
from app.models.user import User
from app.models.user_establishment import UserEstablishment

pytestmark = pytest.mark.asyncio

ADMIN_USERS_URL = "/api/v1/admin/users"
ADMIN_SUBJECTS_URL = "/api/v1/admin/subjects"
REGISTER_MANAGER_URL = "/api/v1/auth/register/establishment-manager"
APPROVE_URL = "/api/v1/admin/managers/{user_id}/establishments/approve"
REJECT_URL = "/api/v1/admin/managers/{user_id}/establishments/reject"
REJECT_MANAGER_URL = "/api/v1/admin/managers/{user_id}/reject"
SUBJECTS_URL = "/api/v1/subjects"


async def _make_list_request(client, *, headers=None):
    return await client.get(ADMIN_USERS_URL, headers=headers or {})


async def _make_approve_request(client, *, headers=None):
    return await client.patch(
        APPROVE_URL.format(user_id=uuid.uuid4()),
        json={"establishment_ids": [str(uuid.uuid4())]},
        headers=headers or {},
    )


async def _make_reject_request(client, *, headers=None):
    return await client.patch(
        REJECT_URL.format(user_id=uuid.uuid4()),
        json={"establishment_ids": [str(uuid.uuid4())]},
        headers=headers or {},
    )


async def _make_reject_manager_request(client, *, headers=None):
    return await client.patch(
        REJECT_MANAGER_URL.format(user_id=uuid.uuid4()),
        headers=headers or {},
    )


@pytest.fixture(
    params=[
        pytest.param(_make_list_request, id="GET /admin/users"),
        pytest.param(
            _make_approve_request,
            id="PATCH /admin/managers/{id}/establishments/approve",
        ),
        pytest.param(
            _make_reject_request,
            id="PATCH /admin/managers/{id}/establishments/reject",
        ),
        pytest.param(
            _make_reject_manager_request,
            id="PATCH /admin/managers/{id}/reject",
        ),
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


@pytest_asyncio.fixture
async def manager_headers(manager_user_id):
    token = create_access_token(manager_user_id, role=UserRole.ESTABLISHMENT_MANAGER)
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def manager_user_id(app):
    """Insert an active establishment manager and return its UUID."""
    return await _insert_user(UserRole.ESTABLISHMENT_MANAGER, UserStatus.ACTIVE)


@pytest_asyncio.fixture
async def non_manager_user_id(app):
    """Insert an active professional user and return its UUID."""
    return await _insert_user(UserRole.PROFESSIONAL, UserStatus.ACTIVE)


async def _insert_user(role: UserRole, user_status: UserStatus) -> uuid.UUID:
    user_id = uuid.uuid4()
    async with db_module.AsyncSessionLocal() as session:
        session.add(
            User(
                id=user_id,
                name="Test",
                last_name="User",
                email=f"{user_id}@test.com",
                role=role,
                status=user_status,
            )
        )
        await session.commit()
    return user_id


def _subject_body(**overrides):
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
    async def _register(self, client, db_establishment, *, name, last_name, email):
        response = await client.post(
            REGISTER_MANAGER_URL,
            json={
                "email": email,
                "password": "Password123!",
                "name": name,
                "last_name": last_name,
                "establishments": [str(db_establishment.id)],
            },
        )
        assert response.status_code == status.HTTP_201_CREATED

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

    async def test_search_by_name_returns_matching(
        self, client, admin_headers, db_establishment
    ):
        """Only users whose name contains the search term are returned."""
        await self._register(
            client,
            db_establishment,
            name="Juanita",
            last_name="Lopez",
            email="juanita@test.com",
        )
        await self._register(
            client,
            db_establishment,
            name="Carlos",
            last_name="Gomez",
            email="carlos@test.com",
        )

        response = await client.get(
            f"{ADMIN_USERS_URL}?search=Juanita", headers=admin_headers
        )

        assert response.status_code == status.HTTP_200_OK
        items = response.json()["items"]
        assert len(items) == 1
        assert items[0]["name"] == "Juanita"

    async def test_search_by_last_name_returns_matching(
        self, client, admin_headers, db_establishment
    ):
        """Only users whose last_name contains the search term are returned."""
        await self._register(
            client,
            db_establishment,
            name="Ana",
            last_name="Ramirez",
            email="ana@test.com",
        )
        await self._register(
            client,
            db_establishment,
            name="Luis",
            last_name="Fernandez",
            email="luis@test.com",
        )

        response = await client.get(
            f"{ADMIN_USERS_URL}?search=Ramirez", headers=admin_headers
        )

        assert response.status_code == status.HTTP_200_OK
        items = response.json()["items"]
        assert len(items) == 1
        assert items[0]["last_name"] == "Ramirez"

    async def test_search_by_email_returns_matching(
        self, client, admin_headers, db_establishment
    ):
        """Only users whose email contains the search term are returned."""
        await self._register(
            client,
            db_establishment,
            name="Maria",
            last_name="Torres",
            email="maria.torres@test.com",
        )
        await self._register(
            client,
            db_establishment,
            name="Pedro",
            last_name="Ruiz",
            email="pedro.ruiz@test.com",
        )

        response = await client.get(
            f"{ADMIN_USERS_URL}?search=maria.torres", headers=admin_headers
        )

        assert response.status_code == status.HTTP_200_OK
        items = response.json()["items"]
        assert len(items) == 1
        assert items[0]["email"] == "maria.torres@test.com"

    async def test_search_is_case_insensitive(
        self, client, admin_headers, db_establishment
    ):
        """Search is case-insensitive: 'juanita' matches a user named 'Juanita'."""
        await self._register(
            client,
            db_establishment,
            name="Juanita",
            last_name="Lopez",
            email="juanita2@test.com",
        )

        response = await client.get(
            f"{ADMIN_USERS_URL}?search=juanita", headers=admin_headers
        )

        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()["items"]) == 1

    async def test_search_no_match_returns_empty(
        self, client, admin_headers, registered_manager
    ):
        """A search term that matches nothing returns an empty list."""
        response = await client.get(
            f"{ADMIN_USERS_URL}?search=zzznomatch", headers=admin_headers
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["items"] == []
        assert data["total"] == 0

    async def test_search_whitespace_only_returns_all(
        self, client, admin_headers, db_establishment
    ):
        """A whitespace-only search is treated as no filter and returns all records."""
        await self._register(
            client,
            db_establishment,
            name="Ana",
            last_name="Paz",
            email="ana.paz@test.com",
        )
        await self._register(
            client,
            db_establishment,
            name="Luis",
            last_name="Vega",
            email="luis.vega@test.com",
        )

        response = await client.get(
            f"{ADMIN_USERS_URL}?search=   ", headers=admin_headers
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["total"] == 2


class TestApproveEstablishments:
    async def test_returns_no_content(
        self, client, admin_headers, registered_manager, db_establishment
    ):
        """Should return 204 on successful approval."""
        url = APPROVE_URL.format(user_id=registered_manager["id"])
        response = await client.patch(
            url,
            json={"establishment_ids": [str(db_establishment.id)]},
            headers=admin_headers,
        )
        assert response.status_code == status.HTTP_204_NO_CONTENT

    async def test_idempotent_when_called_twice(
        self, client, admin_headers, registered_manager, db_establishment
    ):
        """Calling approve twice should return 204 both times."""
        url = APPROVE_URL.format(user_id=registered_manager["id"])
        body = {"establishment_ids": [str(db_establishment.id)]}

        first = await client.patch(url, json=body, headers=admin_headers)
        second = await client.patch(url, json=body, headers=admin_headers)

        assert first.status_code == status.HTTP_204_NO_CONTENT
        assert second.status_code == status.HTTP_204_NO_CONTENT

    async def test_user_not_found(self, client, admin_headers):
        """Should return 404 if the manager does not exist."""
        url = APPROVE_URL.format(user_id=uuid.uuid4())
        response = await client.patch(
            url,
            json={"establishment_ids": [str(uuid.uuid4())]},
            headers=admin_headers,
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_establishment_not_associated_with_manager(
        self, client, admin_headers, registered_manager
    ):
        """Should return 404 if an establishment ID is not linked to this manager."""
        url = APPROVE_URL.format(user_id=registered_manager["id"])
        response = await client.patch(
            url,
            json={"establishment_ids": [str(uuid.uuid4())]},
            headers=admin_headers,
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_empty_ids_rejected(self, client, admin_headers, registered_manager):
        """Should return 422 if establishment_ids is empty."""
        url = APPROVE_URL.format(user_id=registered_manager["id"])
        response = await client.patch(
            url,
            json={"establishment_ids": []},
            headers=admin_headers,
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_user_is_not_a_manager(
        self, client, admin_headers, non_manager_user_id
    ):
        """Should return 400 if the target user is not an establishment manager."""
        url = APPROVE_URL.format(user_id=non_manager_user_id)
        response = await client.patch(
            url,
            json={"establishment_ids": [str(uuid.uuid4())]},
            headers=admin_headers,
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST


class TestRejectEstablishments:
    async def test_returns_no_content(
        self, client, admin_headers, registered_manager, db_establishment
    ):
        """Should return 204 on successful rejection."""
        url = REJECT_URL.format(user_id=registered_manager["id"])
        response = await client.patch(
            url,
            json={"establishment_ids": [str(db_establishment.id)]},
            headers=admin_headers,
        )
        assert response.status_code == status.HTTP_204_NO_CONTENT

    async def test_rejected_establishment_has_rejected_status(
        self, client, admin_headers, registered_manager, db_establishment
    ):
        """The user-establishment relation should be REJECTED in the database."""
        url = REJECT_URL.format(user_id=registered_manager["id"])
        await client.patch(
            url,
            json={"establishment_ids": [str(db_establishment.id)]},
            headers=admin_headers,
        )

        async with db_module.AsyncSessionLocal() as session:
            result = await session.execute(
                select(UserEstablishment).where(
                    UserEstablishment.establishment_id == db_establishment.id
                )
            )
            relation = result.scalar_one()
        assert relation.status.value == "rejected"

    async def test_user_status_unchanged_after_reject(
        self, client, admin_headers, registered_manager, db_establishment
    ):
        """Rejecting establishments must not activate the manager."""
        url = REJECT_URL.format(user_id=registered_manager["id"])
        await client.patch(
            url,
            json={"establishment_ids": [str(db_establishment.id)]},
            headers=admin_headers,
        )

        list_response = await client.get(ADMIN_USERS_URL, headers=admin_headers)
        users = list_response.json()["items"]
        manager = next(u for u in users if u["id"] == registered_manager["id"])
        assert manager["status"] == UserStatus.PENDING_VALIDATION

    async def test_user_not_found(self, client, admin_headers):
        """Should return 404 if the manager does not exist."""
        url = REJECT_URL.format(user_id=uuid.uuid4())
        response = await client.patch(
            url,
            json={"establishment_ids": [str(uuid.uuid4())]},
            headers=admin_headers,
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_establishment_not_associated_with_manager(
        self, client, admin_headers, registered_manager
    ):
        """Should return 404 if an establishment ID is not linked to this manager."""
        url = REJECT_URL.format(user_id=registered_manager["id"])
        response = await client.patch(
            url,
            json={"establishment_ids": [str(uuid.uuid4())]},
            headers=admin_headers,
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_empty_ids_rejected(self, client, admin_headers, registered_manager):
        """Should return 422 if establishment_ids is empty."""
        url = REJECT_URL.format(user_id=registered_manager["id"])
        response = await client.patch(
            url,
            json={"establishment_ids": []},
            headers=admin_headers,
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_user_is_not_a_manager(
        self, client, admin_headers, non_manager_user_id
    ):
        """Should return 400 if the target user is not an establishment manager."""
        url = REJECT_URL.format(user_id=non_manager_user_id)
        response = await client.patch(
            url,
            json={"establishment_ids": [str(uuid.uuid4())]},
            headers=admin_headers,
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST


class TestRejectManager:
    async def test_returns_no_content(
        self, client, admin_headers, registered_manager, db_establishment
    ):
        """Should return 204 on successful rejection."""
        url = REJECT_MANAGER_URL.format(user_id=registered_manager["id"])
        response = await client.patch(url, headers=admin_headers)
        assert response.status_code == status.HTTP_204_NO_CONTENT

    async def test_manager_status_becomes_inactive(
        self, client, admin_headers, registered_manager
    ):
        """Manager status should be INACTIVE after rejection."""
        url = REJECT_MANAGER_URL.format(user_id=registered_manager["id"])
        await client.patch(url, headers=admin_headers)

        list_response = await client.get(
            f"{ADMIN_USERS_URL}?page_size=100", headers=admin_headers
        )
        users = list_response.json()["items"]
        manager = next(u for u in users if u["id"] == registered_manager["id"])
        assert manager["status"] == UserStatus.INACTIVE

    async def test_all_establishments_become_rejected(
        self, client, admin_headers, registered_manager, db_establishment
    ):
        """All user-establishment relations should be REJECTED in the database."""
        url = REJECT_MANAGER_URL.format(user_id=registered_manager["id"])
        await client.patch(url, headers=admin_headers)

        async with db_module.AsyncSessionLocal() as session:
            result = await session.execute(
                select(UserEstablishment).where(
                    UserEstablishment.establishment_id == db_establishment.id
                )
            )
            relation = result.scalar_one()
        assert relation.status.value == "rejected"

    async def test_no_establishments_becomes_inactive(self, client, admin_headers, app):
        """A manager with no establishments should still be marked INACTIVE."""
        user_id = await _insert_user(
            UserRole.ESTABLISHMENT_MANAGER, UserStatus.PENDING_VALIDATION
        )
        url = REJECT_MANAGER_URL.format(user_id=user_id)
        response = await client.patch(url, headers=admin_headers)

        assert response.status_code == status.HTTP_204_NO_CONTENT
        list_response = await client.get(
            f"{ADMIN_USERS_URL}?page_size=100", headers=admin_headers
        )
        users = list_response.json()["items"]
        manager = next(u for u in users if u["id"] == str(user_id))
        assert manager["status"] == UserStatus.INACTIVE

    async def test_user_not_found(self, client, admin_headers):
        """Should return 404 if the manager does not exist."""
        url = REJECT_MANAGER_URL.format(user_id=uuid.uuid4())
        response = await client.patch(url, headers=admin_headers)
        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_user_is_not_a_manager(
        self, client, admin_headers, non_manager_user_id
    ):
        """Should return 400 if the target user is not an establishment manager."""
        url = REJECT_MANAGER_URL.format(user_id=non_manager_user_id)
        response = await client.patch(url, headers=admin_headers)
        assert response.status_code == status.HTTP_400_BAD_REQUEST


class TestAdminSubjectDetail:
    async def test_returns_200_with_subject_and_events(
        self, client, manager_headers, admin_headers
    ):
        """Admin retrieves a subject with its full event history."""
        created = (
            await client.post(
                SUBJECTS_URL, json=_subject_body(), headers=manager_headers
            )
        ).json()
        response = await client.get(
            f"{ADMIN_SUBJECTS_URL}/{created['id']}", headers=admin_headers
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["id"] == created["id"]
        assert data["dni"] == created["dni"]
        assert data["events"]["total"] == 1
        assert data["events"]["items"][0]["event_type"] == "SUBJECT_CREATED"

    async def test_unknown_id_returns_404(self, client, admin_headers):
        """A UUID that was never registered returns 404."""
        response = await client.get(
            f"{ADMIN_SUBJECTS_URL}/{uuid.uuid4()}", headers=admin_headers
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_unauthenticated_returns_401(self, client):
        """No token returns 401."""
        response = await client.get(f"{ADMIN_SUBJECTS_URL}/{uuid.uuid4()}")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_manager_role_returns_403(self, client, manager_headers):
        """A manager token is rejected on the admin endpoint."""
        response = await client.get(
            f"{ADMIN_SUBJECTS_URL}/{uuid.uuid4()}", headers=manager_headers
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
