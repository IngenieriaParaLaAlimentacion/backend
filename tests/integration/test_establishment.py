import uuid

import pytest
from fastapi import status

pytestmark = pytest.mark.asyncio
ESTABLISHMENT_URL = "/api/v1/establishments"


async def _seed_establishment(name: str, address: str) -> None:
    """Insert a single establishment with the given name and address."""
    from app.db.database import AsyncSessionLocal
    from app.models.establishment import Establishment

    async with AsyncSessionLocal() as session:
        session.add(Establishment(name=name, address=address))
        await session.commit()


async def _seed_establishments(n: int, app) -> list:
    """Insert n establishments and return their ORM instances."""
    from app.db.database import AsyncSessionLocal
    from app.models.establishment import Establishment

    created = []
    async with AsyncSessionLocal() as session:
        for i in range(n):
            e = Establishment(name=f"Centro {i}", address=f"Calle {i}")
            session.add(e)
        await session.commit()
        for e in session.new:
            await session.refresh(e)

    async with AsyncSessionLocal() as session:
        from sqlalchemy import select

        result = await session.execute(
            select(Establishment).order_by(Establishment.name)
        )
        created = list(result.scalars().all())

    return created


class TestGetEstablishmentsPaginated:
    async def test_empty_list_returns_200(self, client):
        """No establishments in the DB returns an empty list with zeroed metadata."""
        response = await client.get(ESTABLISHMENT_URL)
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["items"] == []
        assert data["total"] == 0
        assert data["total_pages"] == 0

    async def test_returns_establishment_fields(self, client, db_establishment):
        """Response items include id, name and address serialized correctly."""
        response = await client.get(ESTABLISHMENT_URL)
        assert response.status_code == status.HTTP_200_OK
        item = response.json()["items"][0]
        assert item["id"] == str(db_establishment.id)
        assert item["name"] == db_establishment.name
        assert item["address"] == db_establishment.address

    async def test_pagination_metadata(self, client, app):
        """With 5 establishments and page_size=2, total_pages should be 3."""
        await _seed_establishments(5, app)
        response = await client.get(ESTABLISHMENT_URL + "?page=1&page_size=2")
        data = response.json()
        assert data["total"] == 5
        assert data["page"] == 1
        assert data["page_size"] == 2
        assert data["total_pages"] == 3

    async def test_page_size_limits_results(self, client, app):
        """page_size controls how many items are returned."""
        await _seed_establishments(5, app)
        response = await client.get(ESTABLISHMENT_URL + "?page_size=3")
        assert len(response.json()["items"]) == 3

    async def test_second_page_returns_different_items(self, client, app):
        """Two consecutive pages share no establishments."""
        await _seed_establishments(4, app)
        page1 = await client.get(ESTABLISHMENT_URL + "?page=1&page_size=2")
        page2 = await client.get(ESTABLISHMENT_URL + "?page=2&page_size=2")
        ids1 = {i["id"] for i in page1.json()["items"]}
        ids2 = {i["id"] for i in page2.json()["items"]}
        assert ids1.isdisjoint(ids2)

    async def test_offset_past_last_record_returns_empty(
        self, client, db_establishment
    ):
        """Requesting a page whose offset exceeds the total record count returns
        an empty list."""
        response = await client.get(ESTABLISHMENT_URL + "?page=99&page_size=20")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["items"] == []

    async def test_invalid_page_returns_422(self, client):
        """page=0 is invalid, minimum is 1."""
        response = await client.get(ESTABLISHMENT_URL + "?page=0")
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_invalid_page_size_zero_returns_422(self, client):
        """page_size=0 is invalid, minimum is 1."""
        response = await client.get(ESTABLISHMENT_URL + "?page_size=0")
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_invalid_page_size_above_max_returns_422(self, client):
        """page_size=101 exceeds the maximum of 100."""
        response = await client.get(ESTABLISHMENT_URL + "?page_size=101")
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_search_by_name_returns_matching(self, client):
        """Only establishments whose name contains the search term are returned."""
        await _seed_establishment("Centro Recoleta", "Av. Corrientes 100")
        await _seed_establishment("Centro Caballito", "Av. Santa Fe 200")

        response = await client.get(ESTABLISHMENT_URL + "?search=Recoleta")

        assert response.status_code == status.HTTP_200_OK
        items = response.json()["items"]
        assert len(items) == 1
        assert items[0]["name"] == "Centro Recoleta"

    async def test_search_by_address_returns_matching(self, client):
        """Only establishments whose address contains the search term are returned."""
        await _seed_establishment("Centro A", "Av. Corrientes 100")
        await _seed_establishment("Centro B", "Av. Santa Fe 200")

        response = await client.get(ESTABLISHMENT_URL + "?search=Santa Fe")

        assert response.status_code == status.HTTP_200_OK
        items = response.json()["items"]
        assert len(items) == 1
        assert items[0]["name"] == "Centro B"

    async def test_search_is_case_insensitive(self, client):
        """Search is case-insensitive: 'junin' matches 'Centro Junin'."""
        await _seed_establishment("Centro Junin", "Av. Corrientes 100")

        response = await client.get(ESTABLISHMENT_URL + "?search=junin")

        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()["items"]) == 1

    async def test_search_no_match_returns_empty(self, client):
        """A search term that matches nothing returns an empty list."""
        await _seed_establishment("Gym Centro", "Av. Corrientes 100")

        response = await client.get(ESTABLISHMENT_URL + "?search=zzznomatch")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["items"] == []
        assert data["total"] == 0

    async def test_search_whitespace_only_returns_all(self, client):
        """A whitespace-only search is treated as no filter and returns all records."""
        await _seed_establishment("Centro Recoleta", "Av. Corrientes 100")
        await _seed_establishment("Centro Caballito", "Av. Santa Fe 200")

        response = await client.get(ESTABLISHMENT_URL + "?search=   ")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["total"] == 2


class TestCreateEstablishment:
    async def test_admin_can_create_establishment(self, client, admin_headers):
        """An admin can create a new establishment and receives 201 with all fields."""
        payload = {"name": "Centro Norte", "address": "Av. Cabildo 100"}
        response = await client.post(
            ESTABLISHMENT_URL, json=payload, headers=admin_headers
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["name"] == "Centro Norte"
        assert data["address"] == "Av. Cabildo 100"
        assert "id" in data

    async def test_manager_can_create_establishment(self, client, manager_headers):
        """A manager can create a new establishment and receives 201."""
        payload = {"name": "Centro Norte", "address": "Av. Cabildo 100"}
        response = await client.post(
            ESTABLISHMENT_URL, json=payload, headers=manager_headers
        )

        assert response.status_code == status.HTTP_201_CREATED

    async def test_duplicate_name_and_address_returns_409(self, client, admin_headers):
        """Creating an establishment with the same name and
        address twice returns 409."""
        payload = {"name": "Centro Único", "address": "Calle Falsa 123"}
        await client.post(ESTABLISHMENT_URL, json=payload, headers=admin_headers)
        response = await client.post(
            ESTABLISHMENT_URL, json=payload, headers=admin_headers
        )

        assert response.status_code == status.HTTP_409_CONFLICT

    async def test_same_name_different_address_is_allowed(self, client, admin_headers):
        """Same name but different address is a distinct establishment."""
        await client.post(
            ESTABLISHMENT_URL,
            json={"name": "Centro Salud", "address": "Calle A 1"},
            headers=admin_headers,
        )
        response = await client.post(
            ESTABLISHMENT_URL,
            json={"name": "Centro Salud", "address": "Calle B 2"},
            headers=admin_headers,
        )

        assert response.status_code == status.HTTP_201_CREATED

    async def test_blank_name_returns_422(self, client, admin_headers):
        """A blank name is rejected with 422 before reaching the service."""
        response = await client.post(
            ESTABLISHMENT_URL,
            json={"name": "   ", "address": "Calle X 1"},
            headers=admin_headers,
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_blank_address_returns_422(self, client, admin_headers):
        """A blank address is rejected with 422."""
        response = await client.post(
            ESTABLISHMENT_URL,
            json={"name": "Centro X", "address": "   "},
            headers=admin_headers,
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_missing_token_returns_401(self, client):
        """Requests without an Authorization header are rejected with 401."""
        response = await client.post(
            ESTABLISHMENT_URL, json={"name": "Centro X", "address": "Calle X 1"}
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_professional_role_returns_403(self, client, professional_headers):
        """A PROFESSIONAL token lacks permission to create establishments."""
        response = await client.post(
            ESTABLISHMENT_URL,
            json={"name": "Centro X", "address": "Calle X 1"},
            headers=professional_headers,
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN


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
        assert data["address"] == db_establishment.address

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

    async def test_professional_role_returns_403(
        self, client, db_establishment, professional_headers
    ):
        """A PROFESSIONAL token lacks permission to fetch an establishment."""
        response = await client.get(
            f"{ESTABLISHMENT_URL}/{db_establishment.id}",
            headers=professional_headers,
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
