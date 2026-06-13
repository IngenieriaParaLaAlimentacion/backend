import uuid
from types import SimpleNamespace

import pytest
from fastapi import status

from app.core.security import create_access_token
from app.domain.establishment import UserEstablishmentStatus
from app.domain.user import UserRole, UserStatus

pytestmark = pytest.mark.asyncio
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


async def _insert_manager() -> uuid.UUID:
    from app.db.database import AsyncSessionLocal
    from app.models.user import User

    user_id = uuid.uuid4()
    async with AsyncSessionLocal() as session:
        session.add(
            User(
                id=user_id,
                name="Mgr",
                last_name="One",
                email=f"{user_id}@test.com",
                role=UserRole.ESTABLISHMENT_MANAGER,
                status=UserStatus.ACTIVE,
            )
        )
        await session.commit()
    return user_id


async def _insert_establishment(name: str, formatted_address: str) -> SimpleNamespace:
    from app.db.database import AsyncSessionLocal
    from app.models.establishment import Establishment

    async with AsyncSessionLocal() as session:
        establishment = Establishment(
            name=name,
            formatted_address=formatted_address,
            latitude=-34.6037,
            longitude=-58.3816,
            place_id=str(uuid.uuid4()),
            city="Buenos Aires",
            province="Buenos Aires",
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
    from app.models.user_establishment import UserEstablishment

    async with AsyncSessionLocal() as session:
        session.add(
            UserEstablishment(
                user_id=user_id,
                establishment_id=establishment_id,
                status=status_value,
            )
        )
        await session.commit()


def _manager_headers(user_id: uuid.UUID) -> dict:
    token = create_access_token(user_id, role=UserRole.ESTABLISHMENT_MANAGER)
    return {"Authorization": f"Bearer {token}"}


async def _seed_establishment(name: str, formatted_address: str) -> None:
    """Insert a single establishment with the given name and formatted_address."""
    from app.db.database import AsyncSessionLocal
    from app.models.establishment import Establishment

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
    from app.models.establishment import Establishment

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


class TestGetEstablishmentsPaginated:
    async def test_empty_list_returns_200(self, client, professional_headers):
        """No establishments in the DB returns an empty list with zeroed metadata."""
        response = await client.get(ESTABLISHMENT_URL, headers=professional_headers)
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["items"] == []
        assert data["total"] == 0
        assert data["total_pages"] == 0

    async def test_returns_establishment_fields(
        self, client, db_establishment, professional_headers
    ):
        """Response items include id, name and address serialized correctly."""
        response = await client.get(ESTABLISHMENT_URL, headers=professional_headers)
        assert response.status_code == status.HTTP_200_OK
        item = response.json()["items"][0]
        assert item["id"] == str(db_establishment.id)
        assert item["name"] == db_establishment.name
        assert item["formatted_address"] == db_establishment.formatted_address

    async def test_pagination_metadata(self, client, app, professional_headers):
        """With 5 establishments and page_size=2, total_pages should be 3."""
        await _seed_establishments(5, app)
        response = await client.get(
            ESTABLISHMENT_URL + "?page=1&page_size=2", headers=professional_headers
        )
        data = response.json()
        assert data["total"] == 5
        assert data["page"] == 1
        assert data["page_size"] == 2
        assert data["total_pages"] == 3

    async def test_page_size_limits_results(self, client, app, professional_headers):
        """page_size controls how many items are returned."""
        await _seed_establishments(5, app)
        response = await client.get(
            ESTABLISHMENT_URL + "?page_size=3", headers=professional_headers
        )
        assert len(response.json()["items"]) == 3

    async def test_second_page_returns_different_items(
        self, client, app, professional_headers
    ):
        """Two consecutive pages share no establishments."""
        await _seed_establishments(4, app)
        page1 = await client.get(
            ESTABLISHMENT_URL + "?page=1&page_size=2", headers=professional_headers
        )
        page2 = await client.get(
            ESTABLISHMENT_URL + "?page=2&page_size=2", headers=professional_headers
        )
        ids1 = {i["id"] for i in page1.json()["items"]}
        ids2 = {i["id"] for i in page2.json()["items"]}
        assert ids1.isdisjoint(ids2)

    async def test_offset_past_last_record_returns_empty(
        self, client, db_establishment, professional_headers
    ):
        """Requesting a page whose offset exceeds the total record count returns
        an empty list."""
        response = await client.get(
            ESTABLISHMENT_URL + "?page=99&page_size=20", headers=professional_headers
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["items"] == []

    async def test_invalid_page_returns_422(self, client, professional_headers):
        """page=0 is invalid, minimum is 1."""
        response = await client.get(
            ESTABLISHMENT_URL + "?page=0", headers=professional_headers
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_invalid_page_size_zero_returns_422(
        self, client, professional_headers
    ):
        """page_size=0 is invalid, minimum is 1."""
        response = await client.get(
            ESTABLISHMENT_URL + "?page_size=0", headers=professional_headers
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_invalid_page_size_above_max_returns_422(
        self, client, professional_headers
    ):
        """page_size=101 exceeds the maximum of 100."""
        response = await client.get(
            ESTABLISHMENT_URL + "?page_size=101", headers=professional_headers
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_search_by_name_returns_matching(self, client, professional_headers):
        """Only establishments whose name contains the search term are returned."""
        await _seed_establishment("Centro Recoleta", "Av. Corrientes 100")
        await _seed_establishment("Centro Caballito", "Av. Santa Fe 200")

        response = await client.get(
            ESTABLISHMENT_URL + "?search=Recoleta", headers=professional_headers
        )

        assert response.status_code == status.HTTP_200_OK
        items = response.json()["items"]
        assert len(items) == 1
        assert items[0]["name"] == "Centro Recoleta"

    async def test_search_by_formatted_address_returns_matching(
        self, client, professional_headers
    ):
        """Only establishments whose formatted_address contains the search term."""
        await _seed_establishment("Centro A", "Av. Corrientes 100")
        await _seed_establishment("Centro B", "Av. Santa Fe 200")

        response = await client.get(
            ESTABLISHMENT_URL + "?search=Santa Fe", headers=professional_headers
        )

        assert response.status_code == status.HTTP_200_OK
        items = response.json()["items"]
        assert len(items) == 1
        assert items[0]["name"] == "Centro B"

    async def test_search_is_case_insensitive(self, client, professional_headers):
        """Search is case-insensitive: 'junin' matches 'Centro Junin'."""
        await _seed_establishment("Centro Junin", "Av. Corrientes 100")

        response = await client.get(
            ESTABLISHMENT_URL + "?search=junin", headers=professional_headers
        )

        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()["items"]) == 1

    async def test_search_no_match_returns_empty(self, client, professional_headers):
        """A search term that matches nothing returns an empty list."""
        await _seed_establishment("Gym Centro", "Av. Corrientes 100")

        response = await client.get(
            ESTABLISHMENT_URL + "?search=zzznomatch", headers=professional_headers
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["items"] == []
        assert data["total"] == 0

    async def test_search_whitespace_only_returns_all(
        self, client, professional_headers
    ):
        """A whitespace-only search is treated as no filter and returns all records."""
        await _seed_establishment("Centro Recoleta", "Av. Corrientes 100")
        await _seed_establishment("Centro Caballito", "Av. Santa Fe 200")

        response = await client.get(
            ESTABLISHMENT_URL + "?search=   ", headers=professional_headers
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["total"] == 2


class TestAvailableEstablishments:
    async def test_excludes_approved_and_pending(self, client, app):
        """available=true returns rejected and unrelated establishments only."""
        manager_id = await _insert_manager()
        a = await _insert_establishment("Centro A", "Calle A")
        b = await _insert_establishment("Centro B", "Calle B")
        c = await _insert_establishment("Centro C", "Calle C")
        d = await _insert_establishment("Centro D", "Calle D")
        await _insert_relation(manager_id, a.id, UserEstablishmentStatus.APPROVED)
        await _insert_relation(manager_id, b.id, UserEstablishmentStatus.PENDING)
        await _insert_relation(manager_id, c.id, UserEstablishmentStatus.REJECTED)

        response = await client.get(AVAILABLE_URL, headers=_manager_headers(manager_id))

        assert response.status_code == status.HTTP_200_OK
        ids = {item["id"] for item in response.json()["items"]}
        assert ids == {str(c.id), str(d.id)}

    async def test_search_narrows_available(self, client, app):
        manager_id = await _insert_manager()
        await _insert_establishment("Centro Recoleta", "Av. Corrientes 100")
        await _insert_establishment("Centro Caballito", "Av. Santa Fe 200")

        response = await client.get(
            f"{AVAILABLE_URL}&search=Recoleta", headers=_manager_headers(manager_id)
        )

        assert response.status_code == status.HTTP_200_OK
        items = response.json()["items"]
        assert len(items) == 1
        assert items[0]["name"] == "Centro Recoleta"

    async def test_no_token_returns_401(self, client, app):
        await _insert_establishment("Centro A", "Calle A")
        response = await client.get(AVAILABLE_URL)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_professional_returns_403(self, client, app):
        token = create_access_token(uuid.uuid4(), role=UserRole.PROFESSIONAL)
        response = await client.get(
            AVAILABLE_URL, headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    async def test_listing_requires_token(self, client, app):
        """Regression: the catalog now requires authentication (no anonymous access)."""
        await _insert_establishment("Centro A", "Calle A")
        response = await client.get(ESTABLISHMENT_URL)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


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

    async def test_manager_cannot_create_establishment(self, client, manager_headers):
        """A manager cannot create an establishment and receives 403."""
        payload = _make_payload(
            name="Centro Norte", formatted_address="Av. Cabildo 100"
        )
        response = await client.post(
            ESTABLISHMENT_URL, json=payload, headers=manager_headers
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

    async def test_blank_name_returns_422(self, client, admin_headers):
        """A blank name is rejected with 422 before reaching the service."""
        response = await client.post(
            ESTABLISHMENT_URL,
            json=_make_payload(name="   "),
            headers=admin_headers,
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_blank_formatted_address_returns_422(self, client, admin_headers):
        """A blank formatted_address is rejected with 422."""
        response = await client.post(
            ESTABLISHMENT_URL,
            json=_make_payload(formatted_address="   "),
            headers=admin_headers,
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_missing_token_returns_401(self, client):
        """Requests without an Authorization header are rejected with 401."""
        response = await client.post(ESTABLISHMENT_URL, json=_make_payload())

        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestGetEstablishmentById:
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

    async def test_malformed_uuid_returns_422(self, client, admin_headers):
        """A non-UUID path segment is rejected with 422."""
        response = await client.get(
            f"{ESTABLISHMENT_URL}/not-a-uuid", headers=admin_headers
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_missing_token_returns_401(self, client, db_establishment):
        """Requests without an Authorization header are rejected with 401."""
        response = await client.get(f"{ESTABLISHMENT_URL}/{db_establishment.id}")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_professional_role_returns_200(
        self, client, db_establishment, professional_headers
    ):
        """A PROFESSIONAL token can fetch an establishment."""
        response = await client.get(
            f"{ESTABLISHMENT_URL}/{db_establishment.id}",
            headers=professional_headers,
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

    async def test_update_both_fields_returns_200(
        self, client, db_establishment, admin_headers
    ):
        """Updating both fields at once returns 200 with both values updated."""
        response = await client.patch(
            f"{ESTABLISHMENT_URL}/{db_establishment.id}",
            json={"name": "Nuevo Nombre", "formatted_address": "Nueva Dirección 456"},
            headers=admin_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["name"] == "Nuevo Nombre"
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

    async def test_malformed_uuid_returns_422(self, client, admin_headers):
        """A non-UUID path segment is rejected with 422."""
        response = await client.patch(
            f"{ESTABLISHMENT_URL}/not-a-uuid",
            json={"name": "Nuevo Nombre"},
            headers=admin_headers,
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

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

    async def test_professional_role_returns_403(
        self, client, db_establishment, professional_headers
    ):
        """A PROFESSIONAL token lacks permission to update establishments."""
        response = await client.patch(
            f"{ESTABLISHMENT_URL}/{db_establishment.id}",
            json={"name": "Nuevo Nombre"},
            headers=professional_headers,
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
