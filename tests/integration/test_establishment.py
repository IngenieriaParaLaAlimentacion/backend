import pytest
from fastapi import status

pytestmark = pytest.mark.asyncio


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
        response = await client.get("/api/v1/establishments")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["items"] == []
        assert data["total"] == 0
        assert data["total_pages"] == 0

    async def test_returns_establishment_fields(self, client, db_establishment):
        """Response items include id, name and address serialized correctly."""
        response = await client.get("/api/v1/establishments")
        assert response.status_code == status.HTTP_200_OK
        item = response.json()["items"][0]
        assert item["id"] == str(db_establishment.id)
        assert item["name"] == db_establishment.name
        assert item["address"] == db_establishment.address

    async def test_pagination_metadata(self, client, app):
        """With 5 establishments and page_size=2, total_pages should be 3."""
        await _seed_establishments(5, app)
        response = await client.get("/api/v1/establishments?page=1&page_size=2")
        data = response.json()
        assert data["total"] == 5
        assert data["page"] == 1
        assert data["page_size"] == 2
        assert data["total_pages"] == 3

    async def test_page_size_limits_results(self, client, app):
        """page_size controls how many items are returned."""
        await _seed_establishments(5, app)
        response = await client.get("/api/v1/establishments?page_size=3")
        assert len(response.json()["items"]) == 3

    async def test_second_page_returns_different_items(self, client, app):
        """Two consecutive pages share no establishments."""
        await _seed_establishments(4, app)
        page1 = await client.get("/api/v1/establishments?page=1&page_size=2")
        page2 = await client.get("/api/v1/establishments?page=2&page_size=2")
        ids1 = {i["id"] for i in page1.json()["items"]}
        ids2 = {i["id"] for i in page2.json()["items"]}
        assert ids1.isdisjoint(ids2)

    async def test_offset_past_last_record_returns_empty(
        self, client, db_establishment
    ):
        """Requesting a page whose offset exceeds the total record count returns
        an empty list."""
        response = await client.get("/api/v1/establishments?page=99&page_size=20")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["items"] == []

    async def test_invalid_page_returns_422(self, client):
        """page=0 is invalid, minimum is 1."""
        response = await client.get("/api/v1/establishments?page=0")
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_invalid_page_size_zero_returns_422(self, client):
        """page_size=0 is invalid, minimum is 1."""
        response = await client.get("/api/v1/establishments?page_size=0")
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_invalid_page_size_above_max_returns_422(self, client):
        """page_size=101 exceeds the maximum of 100."""
        response = await client.get("/api/v1/establishments?page_size=101")
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
