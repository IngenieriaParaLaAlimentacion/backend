from datetime import datetime

import pytest
from fastapi import status

from app.domain.establishment import EstablishmentRequestStatus
from app.domain.user import UserRole, UserStatus
from tests.integration.admin.conftest import (
    ADMIN_ESTABLISHMENT_REQUESTS_URL,
    _insert_establishment_request,
    _insert_user,
)

pytestmark = pytest.mark.asyncio


class TestListEstablishmentRequests:
    async def test_returns_paginated_structure(self, client, admin_headers):
        """No requests in the DB still returns a well-formed paginated body."""
        response = await client.get(
            ADMIN_ESTABLISHMENT_REQUESTS_URL, headers=admin_headers
        )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        for field in ("items", "total", "page", "page_size", "total_pages"):
            assert field in body
        assert body["items"] == []
        assert body["total"] == 0

    async def test_items_include_reported_and_requester_fields(
        self, client, admin_headers, app
    ):
        """Each item exposes the reported establishment data plus the
        requesting field worker's identity."""
        user_id = await _insert_user(
            UserRole.FIELD_WORKER,
            UserStatus.ACTIVE,
            name="Maria",
            last_name="Perez",
            email="maria@test.com",
        )
        await _insert_establishment_request(
            user_id,
            name="Comedor Esperanza",
            formatted_address="Av. Siempre Viva 742",
            city="Cordoba",
            province="Cordoba",
        )

        response = await client.get(
            ADMIN_ESTABLISHMENT_REQUESTS_URL, headers=admin_headers
        )

        assert response.status_code == status.HTTP_200_OK
        [item] = response.json()["items"]
        assert item["user_id"] == str(user_id)
        assert item["name"] == "Comedor Esperanza"
        assert item["formatted_address"] == "Av. Siempre Viva 742"
        assert item["city"] == "Cordoba"
        assert item["province"] == "Cordoba"
        assert item["status"] == EstablishmentRequestStatus.PENDING
        assert item["requester_name"] == "Maria"
        assert item["requester_last_name"] == "Perez"
        assert item["requester_email"] == "maria@test.com"

    async def test_filter_by_status_returns_only_matching(
        self, client, admin_headers, app
    ):
        """?status narrows results to requests in that review status."""
        user_id = await _insert_user(UserRole.FIELD_WORKER, UserStatus.ACTIVE)
        await _insert_establishment_request(
            user_id, name="Pendiente", request_status=EstablishmentRequestStatus.PENDING
        )
        await _insert_establishment_request(
            user_id, name="Aprobado", request_status=EstablishmentRequestStatus.APPROVED
        )

        response = await client.get(
            f"{ADMIN_ESTABLISHMENT_REQUESTS_URL}"
            f"?status={EstablishmentRequestStatus.APPROVED.value}",
            headers=admin_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        items = response.json()["items"]
        assert len(items) == 1
        assert items[0]["name"] == "Aprobado"

    async def test_search_matches_reported_name(self, client, admin_headers, app):
        """?search matches the reported establishment name."""
        user_id = await _insert_user(UserRole.FIELD_WORKER, UserStatus.ACTIVE)
        await _insert_establishment_request(user_id, name="Comedor Esperanza")
        await _insert_establishment_request(user_id, name="Merendero Sol")

        response = await client.get(
            f"{ADMIN_ESTABLISHMENT_REQUESTS_URL}?search=Esperanza",
            headers=admin_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        items = response.json()["items"]
        assert len(items) == 1
        assert items[0]["name"] == "Comedor Esperanza"

    async def test_search_matches_requester_identity(self, client, admin_headers, app):
        """?search also matches the requester's name, last name or email, not
        just the reported establishment data."""
        maria_id = await _insert_user(
            UserRole.FIELD_WORKER,
            UserStatus.ACTIVE,
            name="Maria",
            last_name="Torres",
            email="maria.torres@test.com",
        )
        carlos_id = await _insert_user(
            UserRole.FIELD_WORKER,
            UserStatus.ACTIVE,
            name="Carlos",
            last_name="Diaz",
            email="carlos.diaz@test.com",
        )
        await _insert_establishment_request(maria_id, name="Comedor A")
        await _insert_establishment_request(carlos_id, name="Comedor B")

        response = await client.get(
            f"{ADMIN_ESTABLISHMENT_REQUESTS_URL}?search=Torres", headers=admin_headers
        )

        assert response.status_code == status.HTTP_200_OK
        items = response.json()["items"]
        assert len(items) == 1
        assert items[0]["name"] == "Comedor A"

    async def test_city_filter_is_partial_match(self, client, admin_headers, app):
        """?city='CA' matches a request reported in 'CABA': city is a partial
        match, not an exact one."""
        user_id = await _insert_user(UserRole.FIELD_WORKER, UserStatus.ACTIVE)
        await _insert_establishment_request(user_id, name="Comedor CABA", city="CABA")
        await _insert_establishment_request(
            user_id, name="Comedor Rosario", city="Rosario"
        )

        response = await client.get(
            f"{ADMIN_ESTABLISHMENT_REQUESTS_URL}?city=CA", headers=admin_headers
        )

        assert response.status_code == status.HTTP_200_OK
        items = response.json()["items"]
        assert len(items) == 1
        assert items[0]["name"] == "Comedor CABA"

    async def test_province_filter_is_partial_match(self, client, admin_headers, app):
        """?province is also a partial match, mirroring the city filter."""
        user_id = await _insert_user(UserRole.FIELD_WORKER, UserStatus.ACTIVE)
        await _insert_establishment_request(
            user_id, name="Comedor Cordoba", province="Cordoba"
        )
        await _insert_establishment_request(
            user_id, name="Comedor Santa Fe", province="Santa Fe"
        )

        response = await client.get(
            f"{ADMIN_ESTABLISHMENT_REQUESTS_URL}?province=Cord", headers=admin_headers
        )

        assert response.status_code == status.HTTP_200_OK
        items = response.json()["items"]
        assert len(items) == 1
        assert items[0]["name"] == "Comedor Cordoba"

    async def test_default_sort_is_oldest_first(self, client, admin_headers, app):
        """With no ``sort_order``, requests come back oldest first."""
        user_id = await _insert_user(UserRole.FIELD_WORKER, UserStatus.ACTIVE)
        await _insert_establishment_request(
            user_id, name="Primero", created_at=datetime(2024, 1, 1)
        )
        await _insert_establishment_request(
            user_id, name="Segundo", created_at=datetime(2024, 1, 2)
        )

        response = await client.get(
            ADMIN_ESTABLISHMENT_REQUESTS_URL, headers=admin_headers
        )

        names = [item["name"] for item in response.json()["items"]]
        assert names == ["Primero", "Segundo"]

    async def test_sort_order_newest_first(self, client, admin_headers, app):
        """?sort_order=newest reverses the default ordering."""
        user_id = await _insert_user(UserRole.FIELD_WORKER, UserStatus.ACTIVE)
        await _insert_establishment_request(
            user_id, name="Primero", created_at=datetime(2024, 1, 1)
        )
        await _insert_establishment_request(
            user_id, name="Segundo", created_at=datetime(2024, 1, 2)
        )

        response = await client.get(
            f"{ADMIN_ESTABLISHMENT_REQUESTS_URL}?sort_order=newest",
            headers=admin_headers,
        )

        names = [item["name"] for item in response.json()["items"]]
        assert names == ["Segundo", "Primero"]

    async def test_no_match_returns_empty(self, client, admin_headers, app):
        """A search term matching nothing returns an empty page, not an error."""
        user_id = await _insert_user(UserRole.FIELD_WORKER, UserStatus.ACTIVE)
        await _insert_establishment_request(user_id, name="Comedor Esperanza")

        response = await client.get(
            f"{ADMIN_ESTABLISHMENT_REQUESTS_URL}?search=zzznomatch",
            headers=admin_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["items"] == []
        assert data["total"] == 0
