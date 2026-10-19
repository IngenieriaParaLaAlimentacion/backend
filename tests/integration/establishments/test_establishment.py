import uuid
from types import SimpleNamespace

import pytest
from fastapi import status

from app.core.security import create_access_token
from app.domain.establishment import UserEstablishmentStatus
from app.domain.user import UserRole, UserStatus

ESTABLISHMENT_URL = "/api/v1/establishments"

AVAILABLE_URL = "/api/v1/establishments?available=true"


def _make_payload(**overrides) -> dict:
    defaults = {
        "name": "Centro Default",
        "formatted_address": "Av. Corrientes 100",
        "latitude": -34.6037,
        "longitude": -58.3816,
        "place_id": str(uuid.uuid4()),
        "city": "Buenos Aires",
        "province": "Buenos Aires",
    }
    defaults.update(overrides)
    return defaults


async def _insert_field_worker() -> uuid.UUID:
    from app.db.database import AsyncSessionLocal
    from app.models.auth.user import User

    user_id = uuid.uuid4()
    async with AsyncSessionLocal() as session:
        session.add(
            User(
                id=user_id,
                name="Mgr",
                last_name="One",
                email=f"{user_id}@test.com",
                role=UserRole.FIELD_WORKER,
                status=UserStatus.ACTIVE,
            )
        )
        await session.commit()
    return user_id


async def _insert_establishment(
    name: str,
    formatted_address: str,
    *,
    city: str = "Buenos Aires",
    province: str = "Buenos Aires",
) -> SimpleNamespace:
    from app.db.database import AsyncSessionLocal
    from app.models.establishments.establishment import Establishment

    async with AsyncSessionLocal() as session:
        establishment = Establishment(
            name=name,
            formatted_address=formatted_address,
            latitude=-34.6037,
            longitude=-58.3816,
            place_id=str(uuid.uuid4()),
            city=city,
            province=province,
        )
        session.add(establishment)
        await session.commit()
        await session.refresh(establishment)
        return SimpleNamespace(
            id=establishment.id, name=name, formatted_address=formatted_address
        )


async def _insert_relation(
    user_id: uuid.UUID,
    establishment_id: uuid.UUID,
    status_value: UserEstablishmentStatus,
) -> None:
    from app.db.database import AsyncSessionLocal
    from app.models.auth.user_establishment import UserEstablishment

    async with AsyncSessionLocal() as session:
        session.add(
            UserEstablishment(
                user_id=user_id,
                establishment_id=establishment_id,
                status=status_value,
            )
        )
        await session.commit()


def _field_worker_headers(user_id: uuid.UUID) -> dict:
    token = create_access_token(user_id, role=UserRole.FIELD_WORKER)
    return {"Authorization": f"Bearer {token}"}


async def _seed_establishment(name: str, formatted_address: str) -> None:
    """Insert a single establishment with the given name and formatted_address."""
    from app.db.database import AsyncSessionLocal
    from app.models.establishments.establishment import Establishment

    async with AsyncSessionLocal() as session:
        session.add(
            Establishment(
                name=name,
                formatted_address=formatted_address,
                latitude=-34.6037,
                longitude=-58.3816,
                place_id=str(uuid.uuid4()),
                city="Buenos Aires",
                province="Buenos Aires",
            )
        )
        await session.commit()


async def _seed_establishments(n: int, app) -> list:
    """Insert n establishments and return their ORM instances."""
    from app.db.database import AsyncSessionLocal
    from app.models.establishments.establishment import Establishment

    async with AsyncSessionLocal() as session:
        for i in range(n):
            e = Establishment(
                name=f"Centro {i}",
                formatted_address=f"Calle {i}",
                latitude=-34.6037,
                longitude=-58.3816,
                place_id=f"place-seed-{i}",
                city="Buenos Aires",
                province="Buenos Aires",
            )
            session.add(e)
        await session.commit()

    async with AsyncSessionLocal() as session:
        from sqlalchemy import select

        result = await session.execute(
            select(Establishment).order_by(Establishment.name)
        )
        created = list(result.scalars().all())

    return created


async def _set_characterization(
    establishment_id: uuid.UUID, characterization: dict | None
) -> None:
    from app.db.database import AsyncSessionLocal
    from app.models.establishments.establishment import Establishment

    async with AsyncSessionLocal() as session:
        establishment = await session.get(Establishment, establishment_id)
        establishment.characterization = characterization
        await session.commit()


class TestGetEstablishmentsPaginated:
    async def test_empty_list_returns_200(self, client, analyst_headers):
        """No establishments in the DB returns an empty list with zeroed metadata."""
        response = await client.get(ESTABLISHMENT_URL, headers=analyst_headers)
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["items"] == []
        assert data["total"] == 0
        assert data["total_pages"] == 0

    async def test_returns_establishment_fields(
        self, client, db_establishment, analyst_headers
    ):
        """Response items include id, name and address serialized correctly."""
        response = await client.get(ESTABLISHMENT_URL, headers=analyst_headers)
        assert response.status_code == status.HTTP_200_OK
        item = response.json()["items"][0]
        assert item["id"] == str(db_establishment.id)
        assert item["name"] == db_establishment.name
        assert item["formatted_address"] == db_establishment.formatted_address
        assert item["characterization_status"] == "pending"

    async def test_pagination_metadata(self, client, app, analyst_headers):
        """With 5 establishments and page_size=2, total_pages should be 3."""
        await _seed_establishments(5, app)
        response = await client.get(
            ESTABLISHMENT_URL + "?page=1&page_size=2", headers=analyst_headers
        )
        data = response.json()
        assert data["total"] == 5
        assert data["page"] == 1
        assert data["page_size"] == 2
        assert data["total_pages"] == 3
        assert len(data["items"]) == 2

    async def test_second_page_returns_different_items(
        self, client, app, analyst_headers
    ):
        """Two consecutive pages share no establishments."""
        await _seed_establishments(4, app)
        page1 = await client.get(
            ESTABLISHMENT_URL + "?page=1&page_size=2", headers=analyst_headers
        )
        page2 = await client.get(
            ESTABLISHMENT_URL + "?page=2&page_size=2", headers=analyst_headers
        )
        ids1 = {i["id"] for i in page1.json()["items"]}
        ids2 = {i["id"] for i in page2.json()["items"]}
        assert ids1.isdisjoint(ids2)

    async def test_offset_past_last_record_returns_empty(
        self, client, db_establishment, analyst_headers
    ):
        """Requesting a page whose offset exceeds the total record count returns
        an empty list."""
        response = await client.get(
            ESTABLISHMENT_URL + "?page=99&page_size=20", headers=analyst_headers
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["items"] == []

    @pytest.mark.parametrize("query", ["page=0", "page_size=0", "page_size=101"])
    async def test_out_of_range_paging_returns_422(
        self, client, analyst_headers, query
    ):
        """page and page_size must be at least 1, and page_size at most 100."""
        response = await client.get(
            f"{ESTABLISHMENT_URL}?{query}", headers=analyst_headers
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_search_by_name_returns_matching(self, client, analyst_headers):
        """Only establishments whose name contains the search term are returned."""
        await _seed_establishment("Centro Recoleta", "Av. Corrientes 100")
        await _seed_establishment("Centro Caballito", "Av. Santa Fe 200")

        response = await client.get(
            ESTABLISHMENT_URL + "?search=Recoleta", headers=analyst_headers
        )

        assert response.status_code == status.HTTP_200_OK
        items = response.json()["items"]
        assert len(items) == 1
        assert items[0]["name"] == "Centro Recoleta"

    async def test_search_by_formatted_address_returns_matching(
        self, client, analyst_headers
    ):
        """Only establishments whose formatted_address contains the search term."""
        await _seed_establishment("Centro A", "Av. Corrientes 100")
        await _seed_establishment("Centro B", "Av. Santa Fe 200")

        response = await client.get(
            ESTABLISHMENT_URL + "?search=Santa Fe", headers=analyst_headers
        )

        assert response.status_code == status.HTTP_200_OK
        items = response.json()["items"]
        assert len(items) == 1
        assert items[0]["name"] == "Centro B"

    async def test_search_is_case_insensitive(self, client, analyst_headers):
        """Search is case-insensitive: 'junin' matches 'Centro Junin'."""
        await _seed_establishment("Centro Junin", "Av. Corrientes 100")

        response = await client.get(
            ESTABLISHMENT_URL + "?search=junin", headers=analyst_headers
        )

        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()["items"]) == 1

    async def test_search_no_match_returns_empty(self, client, analyst_headers):
        """A search term that matches nothing returns an empty list."""
        await _seed_establishment("Gym Centro", "Av. Corrientes 100")

        response = await client.get(
            ESTABLISHMENT_URL + "?search=zzznomatch", headers=analyst_headers
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["items"] == []
        assert data["total"] == 0

    async def test_search_whitespace_only_returns_all(self, client, analyst_headers):
        """A whitespace-only search is treated as no filter and returns all records."""
        await _seed_establishment("Centro Recoleta", "Av. Corrientes 100")
        await _seed_establishment("Centro Caballito", "Av. Santa Fe 200")

        response = await client.get(
            ESTABLISHMENT_URL + "?search=   ", headers=analyst_headers
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["total"] == 2


class TestAvailableEstablishments:
    async def test_excludes_approved_and_pending(self, client, app):
        """available=true returns rejected and unrelated establishments only."""
        field_worker_id = await _insert_field_worker()
        a = await _insert_establishment("Centro A", "Calle A")
        b = await _insert_establishment("Centro B", "Calle B")
        c = await _insert_establishment("Centro C", "Calle C")
        d = await _insert_establishment("Centro D", "Calle D")
        await _insert_relation(field_worker_id, a.id, UserEstablishmentStatus.APPROVED)
        await _insert_relation(field_worker_id, b.id, UserEstablishmentStatus.PENDING)
        await _insert_relation(field_worker_id, c.id, UserEstablishmentStatus.REJECTED)

        response = await client.get(
            AVAILABLE_URL, headers=_field_worker_headers(field_worker_id)
        )

        assert response.status_code == status.HTTP_200_OK
        ids = {item["id"] for item in response.json()["items"]}
        assert ids == {str(c.id), str(d.id)}

    async def test_search_narrows_available(self, client, app):
        field_worker_id = await _insert_field_worker()
        await _insert_establishment("Centro Recoleta", "Av. Corrientes 100")
        await _insert_establishment("Centro Caballito", "Av. Santa Fe 200")

        response = await client.get(
            f"{AVAILABLE_URL}&search=Recoleta",
            headers=_field_worker_headers(field_worker_id),
        )

        assert response.status_code == status.HTTP_200_OK
        items = response.json()["items"]
        assert len(items) == 1
        assert items[0]["name"] == "Centro Recoleta"

    async def test_city_filter_narrows_available(self, client, app):
        """available now honors the full listing params (city/province/sort)."""
        field_worker_id = await _insert_field_worker()
        await _insert_establishment("Centro Norte", "Calle 1", city="Cordoba")
        await _insert_establishment("Centro Sur", "Calle 2", city="Rosario")

        response = await client.get(
            f"{AVAILABLE_URL}&city=Cordoba",
            headers=_field_worker_headers(field_worker_id),
        )

        assert response.status_code == status.HTTP_200_OK
        items = response.json()["items"]
        assert len(items) == 1
        assert items[0]["name"] == "Centro Norte"

    async def test_no_token_returns_401(self, client, app):
        await _insert_establishment("Centro A", "Calle A")
        response = await client.get(AVAILABLE_URL)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_analyst_can_list_available(self, client, app):
        """Any authenticated role can request establishment access, so any role
        can list the ones still available to it."""
        establishment = await _insert_establishment("Centro A", "Calle A")
        token = create_access_token(uuid.uuid4(), role=UserRole.ANALYST)

        response = await client.get(
            AVAILABLE_URL, headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == status.HTTP_200_OK
        ids = {item["id"] for item in response.json()["items"]}
        assert ids == {str(establishment.id)}

    async def test_public_catalog_unchanged_without_token(self, client, app):
        """Regression: the plain catalog stays public (no token required)."""
        await _insert_establishment("Centro A", "Calle A")
        response = await client.get(ESTABLISHMENT_URL)
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["total"] == 1


class TestCreateEstablishment:
    async def test_admin_can_create_establishment(self, client, admin_headers):
        """An admin can create a new establishment and receives 201 with all fields."""
        payload = _make_payload(
            name="Centro Norte", formatted_address="Av. Cabildo 100"
        )
        response = await client.post(
            ESTABLISHMENT_URL, json=payload, headers=admin_headers
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["name"] == "Centro Norte"
        assert data["formatted_address"] == "Av. Cabildo 100"
        assert "id" in data

    async def test_profile_sent_on_create_is_stored(self, client, admin_headers):
        """The profile is stored with the new establishment and the dashboard
        reads it back."""
        profile = {"meals": ["lunch"], "premises": "other", "premises_other": "Club"}

        response = await client.post(
            ESTABLISHMENT_URL,
            json=_make_payload(characterization=profile),
            headers=admin_headers,
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["characterization_status"] == "complete"
        dashboard = await client.get(
            f"{ESTABLISHMENT_URL}/{response.json()['id']}/dashboard",
            headers=admin_headers,
        )
        stored = dashboard.json()["characterization"]
        assert {key: stored[key] for key in profile} == profile

    @pytest.mark.parametrize(
        "extra", [{}, {"characterization": None}, {"characterization": {"meals": []}}]
    )
    async def test_create_without_answers_is_pending(
        self, client, admin_headers, extra
    ):
        response = await client.post(
            ESTABLISHMENT_URL, json=_make_payload(**extra), headers=admin_headers
        )

        assert response.json()["characterization_status"] == "pending"

    async def test_invalid_profile_returns_422_naming_the_field(
        self, client, admin_headers
    ):
        response = await client.post(
            ESTABLISHMENT_URL,
            json=_make_payload(characterization={"premises_other": "Club"}),
            headers=admin_headers,
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        assert response.json()["field"] == "characterization.premises_other"

    async def test_field_worker_cannot_create_establishment(
        self, client, field_worker_headers
    ):
        """A field worker cannot create an establishment and receives 403."""
        payload = _make_payload(
            name="Centro Norte", formatted_address="Av. Cabildo 100"
        )
        response = await client.post(
            ESTABLISHMENT_URL, json=payload, headers=field_worker_headers
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    async def test_duplicate_place_id_returns_409(self, client, admin_headers):
        """Creating an establishment with the same place_id twice returns 409."""
        payload = _make_payload(name="Centro Único", place_id="place-unique-001")
        await client.post(ESTABLISHMENT_URL, json=payload, headers=admin_headers)
        response = await client.post(
            ESTABLISHMENT_URL, json=payload, headers=admin_headers
        )

        assert response.status_code == status.HTTP_409_CONFLICT

    async def test_same_name_different_place_id_is_allowed(self, client, admin_headers):
        """Same name but different place_id is a distinct establishment."""
        await client.post(
            ESTABLISHMENT_URL,
            json=_make_payload(name="Centro Salud", place_id="place-salud-a"),
            headers=admin_headers,
        )
        response = await client.post(
            ESTABLISHMENT_URL,
            json=_make_payload(name="Centro Salud", place_id="place-salud-b"),
            headers=admin_headers,
        )

        assert response.status_code == status.HTTP_201_CREATED

    @pytest.mark.parametrize("field", ["name", "formatted_address"])
    async def test_blank_field_returns_422(self, client, admin_headers, field):
        """A blank name or formatted_address is rejected with 422."""
        response = await client.post(
            ESTABLISHMENT_URL,
            json=_make_payload(**{field: "   "}),
            headers=admin_headers,
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_missing_token_returns_401(self, client):
        """Requests without an Authorization header are rejected with 401."""
        response = await client.post(ESTABLISHMENT_URL, json=_make_payload())

        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestGetEstablishmentById:
    @pytest.mark.parametrize(
        ("characterization", "expected_status"),
        [
            (None, "pending"),
            ({"meals": [], "district": None}, "pending"),
            ({"meals": ["lunch"], "contact_phone": "11 4567-8901"}, "complete"),
        ],
    )
    async def test_returns_characterization_status_without_the_profile(
        self,
        client,
        db_establishment,
        admin_headers,
        characterization,
        expected_status,
    ):
        """The detail reports whether the profile holds any answer, but not
        the profile itself."""
        await _set_characterization(db_establishment.id, characterization)

        response = await client.get(
            f"{ESTABLISHMENT_URL}/{db_establishment.id}", headers=admin_headers
        )

        data = response.json()
        assert data["characterization_status"] == expected_status
        # The profile carries a private phone; only the dashboard returns it.
        assert "characterization" not in data

    async def test_existing_establishment_returns_200(
        self, client, db_establishment, admin_headers
    ):
        """Fetching a known establishment by ID returns 200 with correct fields."""
        response = await client.get(
            f"{ESTABLISHMENT_URL}/{db_establishment.id}", headers=admin_headers
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["id"] == str(db_establishment.id)
        assert data["name"] == db_establishment.name
        assert data["formatted_address"] == db_establishment.formatted_address

    async def test_unknown_id_returns_404(self, client, admin_headers):
        """A UUID that does not exist in the DB returns 404."""
        response = await client.get(
            f"{ESTABLISHMENT_URL}/{uuid.uuid4()}", headers=admin_headers
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_missing_token_returns_401(self, client, db_establishment):
        """Requests without an Authorization header are rejected with 401."""
        response = await client.get(f"{ESTABLISHMENT_URL}/{db_establishment.id}")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_analyst_role_returns_200(
        self, client, db_establishment, analyst_headers
    ):
        """An ANALYST token can fetch an establishment."""
        response = await client.get(
            f"{ESTABLISHMENT_URL}/{db_establishment.id}",
            headers=analyst_headers,
        )

        assert response.status_code == status.HTTP_200_OK


class TestUpdateEstablishment:
    async def test_update_name_returns_200(
        self, client, db_establishment, admin_headers
    ):
        """Updating only the name returns 200 with the new name and
        unchanged formatted_address."""
        response = await client.patch(
            f"{ESTABLISHMENT_URL}/{db_establishment.id}",
            json={"name": "Nuevo Nombre"},
            headers=admin_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["name"] == "Nuevo Nombre"
        assert data["formatted_address"] == db_establishment.formatted_address

    async def test_update_formatted_address_returns_200(
        self, client, db_establishment, admin_headers
    ):
        """Updating only formatted_address returns 200 with unchanged name."""
        response = await client.patch(
            f"{ESTABLISHMENT_URL}/{db_establishment.id}",
            json={"formatted_address": "Nueva Dirección 456"},
            headers=admin_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["name"] == db_establishment.name
        assert data["formatted_address"] == "Nueva Dirección 456"

    async def test_same_values_returns_200(
        self, client, db_establishment, admin_headers
    ):
        """Sending the exact same name+formatted_address as current values
        is allowed."""
        response = await client.patch(
            f"{ESTABLISHMENT_URL}/{db_establishment.id}",
            json={
                "name": db_establishment.name,
                "formatted_address": db_establishment.formatted_address,
            },
            headers=admin_headers,
        )

        assert response.status_code == status.HTTP_200_OK

    async def test_duplicate_place_id_returns_409(
        self, client, db_establishment, admin_headers
    ):
        """If the place_id already belongs to another establishment, returns 409."""
        other_place_id = "place-other-001"
        await client.post(
            ESTABLISHMENT_URL,
            json=_make_payload(name="Otro Centro", place_id=other_place_id),
            headers=admin_headers,
        )
        response = await client.patch(
            f"{ESTABLISHMENT_URL}/{db_establishment.id}",
            json={"place_id": other_place_id},
            headers=admin_headers,
        )

        assert response.status_code == status.HTTP_409_CONFLICT

    async def test_unknown_id_returns_404(self, client, admin_headers):
        """A valid UUID that does not exist returns 404."""
        response = await client.patch(
            f"{ESTABLISHMENT_URL}/{uuid.uuid4()}",
            json={"name": "Nuevo Nombre"},
            headers=admin_headers,
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_empty_body_returns_422(
        self, client, db_establishment, admin_headers
    ):
        """A body with no fields is rejected with 422."""
        response = await client.patch(
            f"{ESTABLISHMENT_URL}/{db_establishment.id}",
            json={},
            headers=admin_headers,
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_blank_name_returns_422(
        self, client, db_establishment, admin_headers
    ):
        """A blank name is rejected with 422."""
        response = await client.patch(
            f"{ESTABLISHMENT_URL}/{db_establishment.id}",
            json={"name": "   "},
            headers=admin_headers,
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_missing_token_returns_401(self, client, db_establishment):
        """Requests without an Authorization header are rejected with 401."""
        response = await client.patch(
            f"{ESTABLISHMENT_URL}/{db_establishment.id}",
            json={"name": "Nuevo Nombre"},
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_analyst_role_returns_403(
        self, client, db_establishment, analyst_headers
    ):
        """An ANALYST token lacks permission to update establishments."""
        response = await client.patch(
            f"{ESTABLISHMENT_URL}/{db_establishment.id}",
            json={"name": "Nuevo Nombre"},
            headers=analyst_headers,
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN


REQUESTS_URL = f"{ESTABLISHMENT_URL}/requests"


class TestCreateEstablishmentRequest:
    async def test_creates_request_with_full_body(self, client, make_user_with_role):
        """Provided fields are echoed back with status pending."""
        headers, user_id = await make_user_with_role(UserRole.FIELD_WORKER)
        response = await client.post(
            REQUESTS_URL,
            headers=headers,
            json={
                "name": "Comedor Esperanza",
                "formatted_address": "Av. Siempre Viva 742",
                "city": "Cordoba",
                "province": "Cordoba",
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["user_id"] == str(user_id)
        assert data["status"] == "pending"
        assert data["name"] == "Comedor Esperanza"
        assert data["formatted_address"] == "Av. Siempre Viva 742"
        assert data["city"] == "Cordoba"
        assert data["province"] == "Cordoba"

    async def test_request_is_persisted(self, client, make_user_with_role):
        """The notification row is stored with pending status and the creator."""
        headers, user_id = await make_user_with_role(UserRole.FIELD_WORKER)
        await client.post(
            REQUESTS_URL,
            headers=headers,
            json={
                "name": "Comedor Esperanza",
                "formatted_address": "Av. Siempre Viva 742",
            },
        )

        from sqlalchemy import select

        from app.db.database import AsyncSessionLocal
        from app.models.establishments.establishment_request import (
            EstablishmentRequest,
        )

        async with AsyncSessionLocal() as session:
            result = await session.execute(select(EstablishmentRequest))
            row = result.scalar_one()

        assert row.name == "Comedor Esperanza"
        assert row.user_id == user_id
        assert row.status == "pending"
        assert row.created_at is not None

    async def test_field_over_100_chars_returns_422(self, client, make_user_with_role):
        """Fields longer than 100 characters are rejected, like establishments."""
        headers, _ = await make_user_with_role(UserRole.FIELD_WORKER)
        response = await client.post(
            REQUESTS_URL, headers=headers, json={"name": "x" * 101}
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_proposed_profile_is_shown_to_the_admin(
        self, client, make_user_with_role, admin_headers
    ):
        """A profile sent with the request reaches the admin's request listing."""
        headers, _ = await make_user_with_role(UserRole.FIELD_WORKER)
        profile = {"meals": ["lunch"], "premises": "other", "premises_other": "Club"}

        await client.post(
            REQUESTS_URL,
            headers=headers,
            json={
                "name": "Comedor Esperanza",
                "formatted_address": "Av. Siempre Viva 742",
                "characterization": profile,
            },
        )

        listing = await client.get(
            "/api/v1/admin/establishment-requests", headers=admin_headers
        )
        [item] = listing.json()["items"]
        assert {key: item["characterization"][key] for key in profile} == profile

    async def test_invalid_proposed_profile_returns_422_naming_the_field(
        self, client, make_user_with_role
    ):
        headers, _ = await make_user_with_role(UserRole.FIELD_WORKER)

        response = await client.post(
            REQUESTS_URL,
            headers=headers,
            json={
                "name": "Comedor Esperanza",
                "formatted_address": "Av. Siempre Viva 742",
                "characterization": {"premises_other": "Club"},
            },
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        assert response.json()["field"] == "characterization.premises_other"

    async def test_blank_field_returns_422(self, client, make_user_with_role):
        """Whitespace-only fields are rejected with 422."""
        headers, _ = await make_user_with_role(UserRole.FIELD_WORKER)
        response = await client.post(
            REQUESTS_URL, headers=headers, json={"name": "   "}
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_missing_token_returns_401(self, client):
        """Requests without a token are rejected with 401."""
        response = await client.post(REQUESTS_URL, json={})

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
