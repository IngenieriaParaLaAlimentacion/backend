import uuid
from datetime import datetime

from fastapi import status
from sqlalchemy import select

import app.db.database as db_module
from app.domain.establishment import EstablishmentRequestStatus, UserEstablishmentStatus
from app.domain.user import UserRole, UserStatus
from app.models.auth.user_establishment import UserEstablishment
from app.models.establishments.establishment import Establishment
from app.models.establishments.establishment_request import EstablishmentRequest
from tests.integration.admin.conftest import (
    ADMIN_ESTABLISHMENT_REQUESTS_URL,
    APPROVE_ESTABLISHMENT_REQUEST_URL,
    REJECT_ESTABLISHMENT_REQUEST_URL,
    _insert_establishment_request,
    _insert_user,
)


def _approve_body(**overrides):
    body = {
        "name": "Comedor Esperanza",
        "formatted_address": "Av. Siempre Viva 742",
        "latitude": -34.6037,
        "longitude": -58.3816,
        "place_id": "place-test-001",
        "city": "Buenos Aires",
        "province": "Buenos Aires",
    }
    body.update(overrides)
    return body


async def _insert_db_establishment(**overrides) -> Establishment:
    establishment = Establishment(
        **{
            "name": "Comedor Esperanza",
            "formatted_address": "Av. Siempre Viva 742",
            "latitude": -34.6037,
            "longitude": -58.3816,
            "place_id": "place-test-001",
            "city": "Buenos Aires",
            "province": "Buenos Aires",
            **overrides,
        }
    )
    async with db_module.AsyncSessionLocal() as session:
        session.add(establishment)
        await session.commit()
        await session.refresh(establishment)
    return establishment


async def _get_request(request_id: uuid.UUID) -> EstablishmentRequest:
    async with db_module.AsyncSessionLocal() as session:
        return await session.get(EstablishmentRequest, request_id)


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
        assert item["reviewed_by"] is None
        assert "updated_at" in item

    async def test_items_reflect_reviewer_after_approval(
        self, client, admin_headers, make_user_with_role, app
    ):
        """Once a request is approved, the listing surfaces who reviewed it."""
        reviewer_headers, reviewer_id = await make_user_with_role(UserRole.ADMIN)
        user_id = await _insert_user(UserRole.FIELD_WORKER, UserStatus.ACTIVE)
        request_id = await _insert_establishment_request(user_id)

        await client.patch(
            APPROVE_ESTABLISHMENT_REQUEST_URL.format(request_id=request_id),
            json=_approve_body(),
            headers=reviewer_headers,
        )

        response = await client.get(
            ADMIN_ESTABLISHMENT_REQUESTS_URL, headers=admin_headers
        )

        [item] = response.json()["items"]
        assert item["status"] == EstablishmentRequestStatus.APPROVED
        assert item["reviewed_by"] == str(reviewer_id)

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


class TestApproveEstablishmentRequest:
    async def test_returns_200_with_establishment_body(
        self, client, make_user_with_role, app
    ):
        """Approving returns 200 with the resolved establishment's data."""
        admin_headers, _ = await make_user_with_role(UserRole.ADMIN)
        user_id = await _insert_user(UserRole.FIELD_WORKER, UserStatus.ACTIVE)
        request_id = await _insert_establishment_request(user_id)

        response = await client.patch(
            APPROVE_ESTABLISHMENT_REQUEST_URL.format(request_id=request_id),
            json=_approve_body(),
            headers=admin_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["name"] == "Comedor Esperanza"
        assert body["formatted_address"] == "Av. Siempre Viva 742"
        assert body["place_id"] == "place-test-001"
        assert body["city"] == "Buenos Aires"
        assert body["province"] == "Buenos Aires"
        assert body["reused"] is False

    async def test_creates_establishment_row(self, client, make_user_with_role, app):
        """A new Establishment row is persisted with the admin-supplied data."""
        admin_headers, _ = await make_user_with_role(UserRole.ADMIN)
        user_id = await _insert_user(UserRole.FIELD_WORKER, UserStatus.ACTIVE)
        request_id = await _insert_establishment_request(user_id)

        await client.patch(
            APPROVE_ESTABLISHMENT_REQUEST_URL.format(request_id=request_id),
            json=_approve_body(place_id="place-new-001"),
            headers=admin_headers,
        )

        async with db_module.AsyncSessionLocal() as session:
            result = await session.execute(
                select(Establishment).where(Establishment.place_id == "place-new-001")
            )
            establishment = result.scalar_one()
        assert establishment.name == "Comedor Esperanza"

    async def test_leaves_access_pending_for_requester(
        self, client, make_user_with_role, app
    ):
        """The requesting field worker gets a PENDING relation to the
        resolved establishment, for an admin to review separately."""
        admin_headers, _ = await make_user_with_role(UserRole.ADMIN)
        user_id = await _insert_user(UserRole.FIELD_WORKER, UserStatus.ACTIVE)
        request_id = await _insert_establishment_request(user_id)

        response = await client.patch(
            APPROVE_ESTABLISHMENT_REQUEST_URL.format(request_id=request_id),
            json=_approve_body(place_id="place-new-002"),
            headers=admin_headers,
        )
        establishment_id = response.json()["id"]

        async with db_module.AsyncSessionLocal() as session:
            result = await session.execute(
                select(UserEstablishment).where(
                    UserEstablishment.user_id == user_id,
                    UserEstablishment.establishment_id == establishment_id,
                )
            )
            relation = result.scalar_one()
        assert relation.status == UserEstablishmentStatus.PENDING

    async def test_marks_request_as_approved_by_the_admin(
        self, client, make_user_with_role, app
    ):
        """The request's status flips to approved and records the reviewer."""
        admin_headers, admin_id = await make_user_with_role(UserRole.ADMIN)
        user_id = await _insert_user(UserRole.FIELD_WORKER, UserStatus.ACTIVE)
        request_id = await _insert_establishment_request(user_id)

        await client.patch(
            APPROVE_ESTABLISHMENT_REQUEST_URL.format(request_id=request_id),
            json=_approve_body(place_id="place-new-003"),
            headers=admin_headers,
        )

        request = await _get_request(request_id)
        assert request.status == EstablishmentRequestStatus.APPROVED
        assert request.reviewed_by == admin_id

    async def test_dedup_reuses_existing_establishment_with_same_place_id(
        self, client, make_user_with_role, app
    ):
        """Approving with a place_id that already exists reuses that
        establishment instead of creating a duplicate."""
        admin_headers, _ = await make_user_with_role(UserRole.ADMIN)
        existing = await _insert_db_establishment(place_id="place-existing-001")
        user_id = await _insert_user(UserRole.FIELD_WORKER, UserStatus.ACTIVE)
        request_id = await _insert_establishment_request(user_id)

        response = await client.patch(
            APPROVE_ESTABLISHMENT_REQUEST_URL.format(request_id=request_id),
            json=_approve_body(place_id="place-existing-001"),
            headers=admin_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["id"] == str(existing.id)
        assert response.json()["reused"] is True
        async with db_module.AsyncSessionLocal() as session:
            result = await session.execute(
                select(Establishment).where(
                    Establishment.place_id == "place-existing-001"
                )
            )
            assert len(result.scalars().all()) == 1

    async def test_new_establishment_gets_the_approved_profile(
        self, client, make_user_with_role, app
    ):
        """The final profile sent on approval is stored on the new
        establishment and reported as complete."""
        admin_headers, _ = await make_user_with_role(UserRole.ADMIN)
        user_id = await _insert_user(UserRole.FIELD_WORKER, UserStatus.ACTIVE)
        request_id = await _insert_establishment_request(user_id)

        response = await client.patch(
            APPROVE_ESTABLISHMENT_REQUEST_URL.format(request_id=request_id),
            json=_approve_body(characterization={"meals": ["lunch"]}),
            headers=admin_headers,
        )

        assert response.json()["characterization_status"] == "complete"
        async with db_module.AsyncSessionLocal() as session:
            establishment = await session.get(Establishment, response.json()["id"])
        assert establishment.characterization["meals"] == ["lunch"]

    async def test_reused_establishment_keeps_its_answered_profile(
        self, client, make_user_with_role, app
    ):
        admin_headers, _ = await make_user_with_role(UserRole.ADMIN)
        existing = await _insert_db_establishment(
            place_id="place-existing-002", characterization={"meals": ["dinner"]}
        )
        user_id = await _insert_user(UserRole.FIELD_WORKER, UserStatus.ACTIVE)
        request_id = await _insert_establishment_request(user_id)

        await client.patch(
            APPROVE_ESTABLISHMENT_REQUEST_URL.format(request_id=request_id),
            json=_approve_body(
                place_id="place-existing-002", characterization={"meals": ["lunch"]}
            ),
            headers=admin_headers,
        )

        async with db_module.AsyncSessionLocal() as session:
            establishment = await session.get(Establishment, existing.id)
        assert establishment.characterization == {"meals": ["dinner"]}

    async def test_unknown_request_returns_404(self, client, admin_headers):
        """Approving a nonexistent request id returns 404."""
        response = await client.patch(
            APPROVE_ESTABLISHMENT_REQUEST_URL.format(request_id=uuid.uuid4()),
            json=_approve_body(),
            headers=admin_headers,
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_already_reviewed_reports_the_terminal_status(
        self, client, admin_headers, app
    ):
        """ "Already resolved" is not actionable unless the client is told which
        terminal state the request landed in."""
        user_id = await _insert_user(UserRole.FIELD_WORKER, UserStatus.ACTIVE)
        request_id = await _insert_establishment_request(
            user_id, request_status=EstablishmentRequestStatus.REJECTED
        )

        response = await client.patch(
            APPROVE_ESTABLISHMENT_REQUEST_URL.format(request_id=request_id),
            json=_approve_body(),
            headers=admin_headers,
        )

        assert response.status_code == status.HTTP_409_CONFLICT
        body = response.json()
        assert body["type"] == "/errors/establishment-request-already-reviewed"
        assert body["current_status"] == "rejected"


class TestRejectEstablishmentRequest:
    async def test_returns_204_no_content(self, client, make_user_with_role, app):
        """Rejecting returns 204 with no body."""
        admin_headers, _ = await make_user_with_role(UserRole.ADMIN)
        user_id = await _insert_user(UserRole.FIELD_WORKER, UserStatus.ACTIVE)
        request_id = await _insert_establishment_request(user_id)

        response = await client.patch(
            REJECT_ESTABLISHMENT_REQUEST_URL.format(request_id=request_id),
            json={},
            headers=admin_headers,
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert response.content == b""

    async def test_accepts_optional_reason(self, client, make_user_with_role, app):
        """A reason may be supplied without affecting the outcome."""
        admin_headers, _ = await make_user_with_role(UserRole.ADMIN)
        user_id = await _insert_user(UserRole.FIELD_WORKER, UserStatus.ACTIVE)
        request_id = await _insert_establishment_request(user_id)

        response = await client.patch(
            REJECT_ESTABLISHMENT_REQUEST_URL.format(request_id=request_id),
            json={"reason": "Datos incompletos"},
            headers=admin_headers,
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT

    async def test_marks_request_as_rejected_by_the_admin(
        self, client, make_user_with_role, app
    ):
        """The request's status flips to rejected and records the reviewer."""
        admin_headers, admin_id = await make_user_with_role(UserRole.ADMIN)
        user_id = await _insert_user(UserRole.FIELD_WORKER, UserStatus.ACTIVE)
        request_id = await _insert_establishment_request(user_id)

        await client.patch(
            REJECT_ESTABLISHMENT_REQUEST_URL.format(request_id=request_id),
            json={},
            headers=admin_headers,
        )

        request = await _get_request(request_id)
        assert request.status == EstablishmentRequestStatus.REJECTED
        assert request.reviewed_by == admin_id

    async def test_no_establishment_or_relation_created(
        self, client, make_user_with_role, app
    ):
        """Rejecting must not create an establishment or an access relation."""
        admin_headers, _ = await make_user_with_role(UserRole.ADMIN)
        user_id = await _insert_user(UserRole.FIELD_WORKER, UserStatus.ACTIVE)
        request_id = await _insert_establishment_request(user_id)

        await client.patch(
            REJECT_ESTABLISHMENT_REQUEST_URL.format(request_id=request_id),
            json={},
            headers=admin_headers,
        )

        async with db_module.AsyncSessionLocal() as session:
            establishments = (
                (await session.execute(select(Establishment))).scalars().all()
            )
            relations = (
                (await session.execute(select(UserEstablishment))).scalars().all()
            )
        assert establishments == []
        assert relations == []

    async def test_unknown_request_returns_404(self, client, admin_headers):
        """Rejecting a nonexistent request id returns 404."""
        response = await client.patch(
            REJECT_ESTABLISHMENT_REQUEST_URL.format(request_id=uuid.uuid4()),
            json={},
            headers=admin_headers,
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_already_reviewed_returns_409(self, client, admin_headers, app):
        """Rejecting a request that was already resolved returns 409."""
        user_id = await _insert_user(UserRole.FIELD_WORKER, UserStatus.ACTIVE)
        request_id = await _insert_establishment_request(
            user_id, request_status=EstablishmentRequestStatus.REJECTED
        )

        response = await client.patch(
            REJECT_ESTABLISHMENT_REQUEST_URL.format(request_id=request_id),
            json={},
            headers=admin_headers,
        )

        assert response.status_code == status.HTTP_409_CONFLICT
