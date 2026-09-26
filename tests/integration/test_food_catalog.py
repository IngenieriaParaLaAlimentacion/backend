from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest_asyncio
from fastapi import status

FOODS_URL = "/api/v1/food-catalog/foods"
CATEGORIES_URL = "/api/v1/food-catalog/categories"


@dataclass
class Catalog:
    category_meats: UUID
    category_fruits: UUID
    food_chicken: UUID  # "Pechuga de pollo", Carnes, has nutrient values
    food_beef: UUID  # "Bife de vaca", Carnes, no nutrient values
    food_apple: UUID  # "Manzana", Frutas
    nutrient_protein: UUID  # macronutrient, "Proteínas", g
    nutrient_dha: UUID  # fatty_acid, "22:6 DHA", g
    nutrient_vitamin_c: UUID  # vitamin, "Vitamina C", mg


@pytest_asyncio.fixture
async def catalog(app) -> Catalog:
    """Seed food categories, foods, nutrients and nutrient values directly —
    this module has no create endpoint, the catalog is only ever populated
    via the seed script."""
    from decimal import Decimal

    from app.db.database import AsyncSessionLocal
    from app.domain.food_catalog import MeasurementUnit, NutrientGroup
    from app.models.food_catalog.food import Food
    from app.models.food_catalog.food_category import FoodCategory
    from app.models.food_catalog.food_nutrient_value import FoodNutrientValue
    from app.models.food_catalog.nutrient import Nutrient

    async with AsyncSessionLocal() as session:
        meats = FoodCategory(code="carnes", name="Carnes")
        fruits = FoodCategory(code="frutas", name="Frutas")
        session.add_all([meats, fruits])

        protein = Nutrient(
            code="protein",
            name="Proteínas",
            unit="g",
            group=NutrientGroup.MACRONUTRIENT,
        )
        dha = Nutrient(
            code="dha", name="22:6 DHA", unit="g", group=NutrientGroup.FATTY_ACID
        )
        vitamin_c = Nutrient(
            code="vitamin_c", name="Vitamina C", unit="mg", group=NutrientGroup.VITAMIN
        )
        session.add_all([protein, dha, vitamin_c])
        await session.flush()

        chicken = Food(
            code="pollo_pechuga",
            name="Pechuga de pollo",
            category_id=meats.id,
            base_unit=MeasurementUnit.KILOGRAMOS,
        )
        beef = Food(
            code="vaca_bife",
            name="Bife de vaca",
            category_id=meats.id,
            base_unit=MeasurementUnit.KILOGRAMOS,
        )
        apple = Food(
            code="manzana",
            name="Manzana",
            category_id=fruits.id,
            base_unit=MeasurementUnit.KILOGRAMOS,
        )
        session.add_all([chicken, beef, apple])
        await session.flush()

        # Only chicken has measured nutrients — mirrors SARA 2's real sparsity
        # (a food not covered here simply has no row, never a `0`).
        session.add_all(
            [
                FoodNutrientValue(
                    food_id=chicken.id,
                    nutrient_id=protein.id,
                    amount_per_100g=Decimal("31.0200"),
                ),
                FoodNutrientValue(
                    food_id=chicken.id,
                    nutrient_id=dha.id,
                    amount_per_100g=Decimal("0.0100"),
                ),
                FoodNutrientValue(
                    food_id=chicken.id,
                    nutrient_id=vitamin_c.id,
                    amount_per_100g=Decimal("0.0000"),
                ),
            ]
        )
        await session.commit()

        return Catalog(
            category_meats=meats.id,
            category_fruits=fruits.id,
            food_chicken=chicken.id,
            food_beef=beef.id,
            food_apple=apple.id,
            nutrient_protein=protein.id,
            nutrient_dha=dha.id,
            nutrient_vitamin_c=vitamin_c.id,
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
        assert body["total"] == 3
        assert body["page"] == 1
        assert body["page_size"] == 2
        assert body["total_pages"] == 2
        assert len(body["items"]) == 2


class TestCategories:
    async def test_unauthenticated_returns_401(self, client):
        response = await client.get(CATEGORIES_URL)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_default_sort_is_alphabetical(self, client, admin_headers, catalog):
        response = await client.get(CATEGORIES_URL, headers=admin_headers)
        assert response.status_code == status.HTTP_200_OK
        items = response.json()
        assert [i["name"] for i in items] == ["Carnes", "Frutas"]
        assert items[0] == {"id": str(catalog.category_meats), "name": "Carnes"}

    async def test_sort_order_name_desc_reverses_it(
        self, client, admin_headers, catalog
    ):
        response = await client.get(
            CATEGORIES_URL, params={"sort_order": "name_desc"}, headers=admin_headers
        )
        items = response.json()
        assert [i["name"] for i in items] == ["Frutas", "Carnes"]

    async def test_response_is_not_paginated(self, client, admin_headers, catalog):
        response = await client.get(CATEGORIES_URL, headers=admin_headers)
        assert isinstance(response.json(), list)


class TestFoodDetail:
    async def test_unauthenticated_returns_401(self, client, catalog):
        response = await client.get(f"{FOODS_URL}/{catalog.food_chicken}")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_missing_food_returns_404(self, client, admin_headers):
        response = await client.get(f"{FOODS_URL}/{uuid4()}", headers=admin_headers)
        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_returns_full_detail_with_nutrients(
        self, client, admin_headers, catalog
    ):
        response = await client.get(
            f"{FOODS_URL}/{catalog.food_chicken}", headers=admin_headers
        )
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["code"] == "pollo_pechuga"
        assert body["name"] == "Pechuga de pollo"
        assert body["category"] == {
            "id": str(catalog.category_meats),
            "name": "Carnes",
        }

        nutrients = body["nutrients"]
        assert len(nutrients) == 3
        # Sorted macronutrient -> fatty_acid -> vitamin (SARA 2's own split).
        assert [n["nutrient"]["name"] for n in nutrients] == [
            "Proteínas",
            "22:6 DHA",
            "Vitamina C",
        ]
        protein = nutrients[0]
        assert protein["nutrient"] == {
            "id": str(catalog.nutrient_protein),
            "name": "Proteínas",
            "unit": "g",
            "group": "macronutrient",
        }
        assert protein["amount_per_100g"] == "31.0200"

    async def test_food_with_no_measured_nutrients_returns_empty_list(
        self, client, admin_headers, catalog
    ):
        """Blank source cells mean absent rows, never a synthetic `0` — a food
        with none measured returns an empty ``nutrients`` list, not zeros."""
        response = await client.get(
            f"{FOODS_URL}/{catalog.food_beef}", headers=admin_headers
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["nutrients"] == []
