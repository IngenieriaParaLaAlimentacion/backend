from dataclasses import dataclass
from uuid import UUID

import pytest
import pytest_asyncio
from fastapi import status

pytestmark = pytest.mark.asyncio

FOODS_URL = "/api/v1/food-catalog/foods"
CATEGORIES_URL = "/api/v1/food-catalog/categories"


@dataclass
class Catalog:
    category_meats: UUID
    category_fruits: UUID
    food_chicken: UUID  # "Pechuga de pollo", Carnes, active
    food_beef: UUID  # "Bife de vaca", Carnes, active
    food_apple: UUID  # "Manzana", Frutas, active
    food_retired: UUID  # "Alimento discontinuado", Carnes, inactive


@pytest_asyncio.fixture
async def catalog(app) -> Catalog:
    """Seed food categories and foods directly — this module has no create
    endpoint, the catalog is only ever populated via the seed script."""
    from app.db.database import AsyncSessionLocal
    from app.domain.food_catalog import MeasurementUnit
    from app.models.food_catalog.food import Food
    from app.models.food_catalog.food_category import FoodCategory

    async with AsyncSessionLocal() as session:
        meats = FoodCategory(code="carnes", name="Carnes", sara2_group_number=7)
        fruits = FoodCategory(code="frutas", name="Frutas", sara2_group_number=2)
        session.add_all([meats, fruits])
        await session.flush()

        chicken = Food(
            code="pollo_pechuga",
            name="Pechuga de pollo",
            category_id=meats.id,
            base_unit=MeasurementUnit.KILOGRAMOS,
            is_active=True,
        )
        beef = Food(
            code="vaca_bife",
            name="Bife de vaca",
            category_id=meats.id,
            base_unit=MeasurementUnit.KILOGRAMOS,
            is_active=True,
        )
        apple = Food(
            code="manzana",
            name="Manzana",
            category_id=fruits.id,
            base_unit=MeasurementUnit.KILOGRAMOS,
            is_active=True,
        )
        retired = Food(
            code="discontinuado",
            name="Alimento discontinuado",
            category_id=meats.id,
            base_unit=MeasurementUnit.UNIDADES,
            is_active=False,
        )
        session.add_all([chicken, beef, apple, retired])
        await session.commit()

        return Catalog(
            category_meats=meats.id,
            category_fruits=fruits.id,
            food_chicken=chicken.id,
            food_beef=beef.id,
            food_apple=apple.id,
            food_retired=retired.id,
        )


class TestAuth:
    async def test_unauthenticated_returns_401(self, client):
        response = await client.get(FOODS_URL)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_field_worker_is_allowed(self, client, field_worker_headers):
        response = await client.get(FOODS_URL, headers=field_worker_headers)
        assert response.status_code == status.HTTP_200_OK


class TestShape:
    async def test_item_shape_includes_nested_category(
        self, client, admin_headers, catalog
    ):
        response = await client.get(
            FOODS_URL,
            params={"search": "pollo"},
            headers=admin_headers,
        )
        item = response.json()["items"][0]
        assert item["code"] == "pollo_pechuga"
        assert item["name"] == "Pechuga de pollo"
        assert item["base_unit"] == "kilogramos"
        assert item["is_active"] is True
        assert item["category"] == {
            "id": str(catalog.category_meats),
            "name": "Carnes",
        }


class TestFilters:
    async def test_search_matches_name_case_insensitively(
        self, client, admin_headers, catalog
    ):
        response = await client.get(
            FOODS_URL, params={"search": "MANZA"}, headers=admin_headers
        )
        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["name"] == "Manzana"

    async def test_category_id_filters_to_that_category(
        self, client, admin_headers, catalog
    ):
        response = await client.get(
            FOODS_URL,
            params={"category_id": str(catalog.category_fruits)},
            headers=admin_headers,
        )
        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["name"] == "Manzana"

    async def test_inactive_foods_excluded_by_default(
        self, client, admin_headers, catalog
    ):
        response = await client.get(FOODS_URL, headers=admin_headers)
        names = {item["name"] for item in response.json()["items"]}
        assert "Alimento discontinuado" not in names

    async def test_is_active_false_returns_only_retired(
        self, client, admin_headers, catalog
    ):
        response = await client.get(
            FOODS_URL, params={"is_active": False}, headers=admin_headers
        )
        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["name"] == "Alimento discontinuado"


class TestSortAndPagination:
    async def test_sort_by_name_asc(self, client, admin_headers, catalog):
        response = await client.get(
            FOODS_URL, params={"sort_order": "name_asc"}, headers=admin_headers
        )
        names = [item["name"] for item in response.json()["items"]]
        assert names == sorted(names, key=str.lower)

    async def test_pagination_metadata(self, client, admin_headers, catalog):
        response = await client.get(
            FOODS_URL, params={"page": 1, "page_size": 2}, headers=admin_headers
        )
        body = response.json()
        assert body["total"] == 3  # 3 active foods, retired one excluded
        assert body["page"] == 1
        assert body["page_size"] == 2
        assert body["total_pages"] == 2
        assert len(body["items"]) == 2


class TestCategories:
    async def test_unauthenticated_returns_401(self, client):
        response = await client.get(CATEGORIES_URL)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_returns_categories_in_sara2_source_order(
        self, client, admin_headers, catalog
    ):
        # Fixture seeds "Frutas" as group 2 and "Carnes" as group 7.
        response = await client.get(CATEGORIES_URL, headers=admin_headers)
        assert response.status_code == status.HTTP_200_OK
        items = response.json()
        assert [i["name"] for i in items] == ["Frutas", "Carnes"]
        assert items[0] == {"id": str(catalog.category_fruits), "name": "Frutas"}

    async def test_response_is_not_paginated(self, client, admin_headers, catalog):
        response = await client.get(CATEGORIES_URL, headers=admin_headers)
        assert isinstance(response.json(), list)
