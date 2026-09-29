import uuid
from unittest.mock import patch

import pytest
from fastapi import status

import app.db.database as db_module
from app.domain.user import UserRole, UserStatus
from app.models.auth.user import User
from tests.integration.admin.conftest import (
    ADMIN_USER_URL,
    ADMIN_USERS_URL,
    APPROVE_FIELD_WORKER_URL,
    APPROVE_URL,
    REGISTER_FIELD_WORKER_URL,
    REJECT_URL,
    _insert_user,
)
from tests.integration.urls import INVITE_ADMIN_URL


class TestListUsersPagination:
    async def _register(self, client, db_establishment, *, name, last_name, email):
        response = await client.post(
            REGISTER_FIELD_WORKER_URL,
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

    @pytest.mark.parametrize("query", ["page_size=200", "page=0"])
    async def test_out_of_range_paging_rejected(self, client, admin_headers, query):
        """page must be at least 1 and page_size at most 100."""
        response = await client.get(f"{ADMIN_USERS_URL}?{query}", headers=admin_headers)
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_items_have_required_fields(
        self, client, admin_headers, registered_field_worker
    ):
        """Each item should expose id, email, name, last_name, role,
        status, is_email_verified and establishments."""
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
            assert "is_email_verified" in item
            assert "establishments" in item

    async def test_listing_hides_pending_establishments(
        self, client, admin_headers, registered_field_worker
    ):
        """The listing shows access, not requests: a pending relation is absent."""
        response = await client.get(ADMIN_USERS_URL, headers=admin_headers)

        item = next(
            i
            for i in response.json()["items"]
            if i["id"] == registered_field_worker["id"]
        )
        assert item["establishments"] == []

    async def test_listing_shows_approved_establishments(
        self, client, admin_headers, accepted_field_worker, db_establishment
    ):
        """An approved relation does show up in the listing."""
        await client.patch(
            APPROVE_URL.format(user_id=accepted_field_worker["id"]),
            json={"establishment_ids": [str(db_establishment.id)]},
            headers=admin_headers,
        )

        response = await client.get(ADMIN_USERS_URL, headers=admin_headers)

        item = next(
            i
            for i in response.json()["items"]
            if i["id"] == accepted_field_worker["id"]
        )
        assert [e["id"] for e in item["establishments"]] == [str(db_establishment.id)]

    async def test_filter_by_role_returns_only_matching_users(
        self, client, admin_headers, registered_field_worker
    ):
        """Should return only users with the requested role."""
        response = await client.get(
            f"{ADMIN_USERS_URL}?role={UserRole.FIELD_WORKER.value}",
            headers=admin_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        items = response.json()["items"]
        assert all(item["role"] == UserRole.FIELD_WORKER for item in items)

    async def test_filter_by_role_no_users(
        self, client, admin_headers, registered_field_worker
    ):
        """Should return empty when filtering by a role with no users."""
        response = await client.get(
            f"{ADMIN_USERS_URL}?role={UserRole.ANALYST.value}",
            headers=admin_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["items"] == []

    async def test_filter_by_status_returns_only_matching_users(
        self, client, admin_headers, registered_field_worker
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
        self, client, admin_headers, registered_field_worker
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
        self, client, admin_headers, registered_field_worker
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

    async def test_pending_field_worker_request_query_returns_verified_pending(
        self, client, admin_headers, registered_field_worker
    ):
        """role=field_worker&status=pending_validation (the query the frontend
        uses to list field worker requests) returns field workers awaiting
        admin approval, since their email is already verified by default."""
        response = await client.get(
            f"{ADMIN_USERS_URL}?role={UserRole.FIELD_WORKER.value}"
            f"&status={UserStatus.PENDING_VALIDATION.value}",
            headers=admin_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        ids = [item["id"] for item in response.json()["items"]]
        assert registered_field_worker["id"] in ids

    async def test_pending_field_worker_request_query_excludes_active(
        self, client, admin_headers, registered_field_worker, db_establishment
    ):
        """A field worker already approved (active) should not appear as pending."""
        approve = await client.patch(
            APPROVE_FIELD_WORKER_URL.format(user_id=registered_field_worker["id"]),
            json={"establishment_ids": [str(db_establishment.id)]},
            headers=admin_headers,
        )
        assert approve.status_code == status.HTTP_204_NO_CONTENT

        response = await client.get(
            f"{ADMIN_USERS_URL}?role={UserRole.FIELD_WORKER.value}"
            f"&status={UserStatus.PENDING_VALIDATION.value}",
            headers=admin_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        ids = [item["id"] for item in response.json()["items"]]
        assert registered_field_worker["id"] not in ids

    async def test_pending_field_worker_request_query_excludes_admin_invites(
        self, client, admin_headers
    ):
        """A pending admin invite must not show up when filtering for field
        worker requests, since admins never go through establishment approval."""
        with patch("app.services.admin_service.send_invite_email"):
            invite_response = await client.post(
                INVITE_ADMIN_URL,
                json={"email": f"admin_{uuid.uuid4().hex[:6]}@test.com"},
                headers=admin_headers,
            )
        assert invite_response.status_code == status.HTTP_202_ACCEPTED
        invited_id = invite_response.json()["user_id"]

        response = await client.get(
            f"{ADMIN_USERS_URL}?role={UserRole.FIELD_WORKER.value}"
            f"&status={UserStatus.PENDING_VALIDATION.value}",
            headers=admin_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        ids = [item["id"] for item in response.json()["items"]]
        assert invited_id not in ids


class TestGetUser:
    async def test_unauthenticated_returns_401(self, client):
        """No token returns 401."""
        response = await client.get(ADMIN_USER_URL.format(user_id=uuid.uuid4()))
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_field_worker_role_returns_403(self, client, field_worker_headers):
        """A field worker token is rejected."""
        response = await client.get(
            ADMIN_USER_URL.format(user_id=uuid.uuid4()), headers=field_worker_headers
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    async def test_analyst_role_returns_403(self, client, analyst_headers):
        """An analyst token is rejected."""
        response = await client.get(
            ADMIN_USER_URL.format(user_id=uuid.uuid4()), headers=analyst_headers
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    async def test_unknown_id_returns_404(self, client, admin_headers):
        """A UUID that was never registered returns 404."""
        response = await client.get(
            ADMIN_USER_URL.format(user_id=uuid.uuid4()), headers=admin_headers
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_response_includes_required_fields(self, client, admin_headers, app):
        """Response includes all fields defined in FullUserAdminView."""
        user_id = await _insert_user(UserRole.ANALYST, UserStatus.ACTIVE)
        response = await client.get(
            ADMIN_USER_URL.format(user_id=user_id), headers=admin_headers
        )
        body = response.json()
        for field in (
            "id",
            "email",
            "name",
            "last_name",
            "role",
            "status",
            "establishments",
        ):
            assert field in body

    async def test_returns_user_data_correctly(self, client, admin_headers, app):
        """Returned data matches what was stored. Locality, description and
        contact_phone are null for users that never set them."""
        user_id = await _insert_user(UserRole.ANALYST, UserStatus.ACTIVE)
        response = await client.get(
            ADMIN_USER_URL.format(user_id=user_id), headers=admin_headers
        )
        body = response.json()
        assert body["id"] == str(user_id)
        assert body["role"] == UserRole.ANALYST
        assert body["status"] == UserStatus.ACTIVE
        assert body["locality"] is None
        assert body["description"] is None
        assert body["contact_phone"] is None

    async def test_pending_establishments_are_not_returned(
        self, client, admin_headers, registered_field_worker
    ):
        """A registration only requests access. Until an admin approves it the
        establishment is not part of the user's access and must not show up."""
        response = await client.get(
            ADMIN_USER_URL.format(user_id=registered_field_worker["id"]),
            headers=admin_headers,
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["establishments"] == []

    async def test_returns_user_with_hydrated_establishments(
        self, client, admin_headers, accepted_field_worker, db_establishment
    ):
        """Once the access is approved the establishment comes back hydrated."""
        await client.patch(
            APPROVE_URL.format(user_id=accepted_field_worker["id"]),
            json={"establishment_ids": [str(db_establishment.id)]},
            headers=admin_headers,
        )

        response = await client.get(
            ADMIN_USER_URL.format(user_id=accepted_field_worker["id"]),
            headers=admin_headers,
        )
        assert response.status_code == status.HTTP_200_OK
        establishments = response.json()["establishments"]
        assert len(establishments) == 1
        assert establishments[0]["id"] == str(db_establishment.id)
        assert establishments[0]["name"] == db_establishment.name

    async def test_rejected_establishments_are_not_returned(
        self, client, admin_headers, accepted_field_worker, db_establishment
    ):
        """A rejected request is not access either."""
        await client.patch(
            REJECT_URL.format(user_id=accepted_field_worker["id"]),
            json={"establishment_ids": [str(db_establishment.id)]},
            headers=admin_headers,
        )

        response = await client.get(
            ADMIN_USER_URL.format(user_id=accepted_field_worker["id"]),
            headers=admin_headers,
        )
        assert response.json()["establishments"] == []

    async def test_optional_fields_returned_when_set(self, client, admin_headers, app):
        """locality, description and contact_phone are returned when stored in DB."""
        user_id = uuid.uuid4()
        async with db_module.AsyncSessionLocal() as session:
            session.add(
                User(
                    id=user_id,
                    name="Test",
                    last_name="User",
                    email=f"{user_id}@test.com",
                    role=UserRole.ANALYST,
                    status=UserStatus.ACTIVE,
                    locality="Palermo",
                    description="Nutricionista",
                    contact_phone="1123456789",
                )
            )
            await session.commit()

        response = await client.get(
            ADMIN_USER_URL.format(user_id=user_id), headers=admin_headers
        )
        body = response.json()
        assert body["locality"] == "Palermo"
        assert body["description"] == "Nutricionista"
        assert body["contact_phone"] == "1123456789"
