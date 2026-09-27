import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.food_catalog import FoodListingParams, MeasurementUnit, NutrientGroup
from app.domain.pagination import PaginatedResult
from app.exceptions.domain_exceptions import FoodNotFoundError
from app.services.food_catalog.food_service import FoodService


@pytest.fixture
def make_food():
    def _make(name: str = "Pechuga de pollo", category_name: str = "Carnes"):
        category = MagicMock()
        category.id = uuid.uuid4()
        category.name = category_name

        food = MagicMock()
        food.id = uuid.uuid4()
        food.code = "pollo_pechuga"
        food.name = name
        food.base_unit = MeasurementUnit.KILOGRAMOS
        food.category = category
        food.nutrient_values = []
        return food

    return _make


@pytest.fixture
def make_nutrient_value():
    def _make(
        name: str = "Proteínas",
        unit: str = "g",
        group: NutrientGroup = NutrientGroup.MACRONUTRIENT,
        amount: Decimal = Decimal("10.0"),
    ):
        nutrient = MagicMock()
        nutrient.id = uuid.uuid4()
        nutrient.name = name
        nutrient.unit = unit
        nutrient.group = group

        value = MagicMock()
        value.nutrient = nutrient
        value.amount_per_100g = amount
        return value

    return _make


@pytest.fixture
def make_uow(make_food):
    def _make():
        uow = AsyncMock()
        uow.food_repo.list = AsyncMock(return_value=([make_food()], 1))
        return uow

    return _make


class TestListFoods:
    async def test_passes_computed_offset(self, make_uow):
        uow = make_uow()
        await FoodService(uow).list_foods(
            page=3, page_size=10, params=FoodListingParams()
        )
        uow.food_repo.list.assert_awaited_once()
        _, kwargs = uow.food_repo.list.call_args
        assert kwargs["limit"] == 10
        assert kwargs["offset"] == 20
        assert kwargs["params"] is not None

    async def test_page_below_one_is_clamped(self, make_uow):
        uow = make_uow()
        await FoodService(uow).list_foods(
            page=0, page_size=10, params=FoodListingParams()
        )
        _, kwargs = uow.food_repo.list.call_args
        assert kwargs["offset"] == 0

    async def test_builds_paginated_result_with_category_ref(self, make_uow):
        result = await FoodService(make_uow()).list_foods(
            page=1, page_size=10, params=FoodListingParams()
        )
        assert isinstance(result, PaginatedResult)
        assert result.total == 1
        item = result.items[0]
        assert item.name == "Pechuga de pollo"
        assert item.category.name == "Carnes"


class TestGetFood:
    async def test_nutrients_sorted_by_group_then_name(
        self, make_food, make_nutrient_value
    ):
        food = make_food()
        food.nutrient_values = [
            make_nutrient_value(name="Zinc", group=NutrientGroup.MINERAL),
            make_nutrient_value(name="Proteínas", group=NutrientGroup.MACRONUTRIENT),
            make_nutrient_value(name="22:6 DHA", group=NutrientGroup.FATTY_ACID),
            make_nutrient_value(name="Vitamina C", group=NutrientGroup.VITAMIN),
            make_nutrient_value(
                name="Grasas totales", group=NutrientGroup.MACRONUTRIENT
            ),
        ]
        uow = AsyncMock()
        uow.food_repo.get_by_id = AsyncMock(return_value=food)

        result = await FoodService(uow).get_food(food.id)

        names = [v.nutrient.name for v in result.nutrients]
        assert names == [
            "Grasas totales",
            "Proteínas",
            "22:6 DHA",
            "Vitamina C",
            "Zinc",
        ]

    async def test_blank_source_cells_are_simply_absent(self, make_food):
        """A food with fewer than 39 measured nutrients returns exactly the
        rows it has — never a synthetic zero for the missing ones."""
        food = make_food()
        food.nutrient_values = []
        uow = AsyncMock()
        uow.food_repo.get_by_id = AsyncMock(return_value=food)

        result = await FoodService(uow).get_food(food.id)

        assert result.nutrients == []

    async def test_missing_food_raises_not_found(self):
        uow = AsyncMock()
        uow.food_repo.get_by_id = AsyncMock(return_value=None)

        with pytest.raises(FoodNotFoundError):
            await FoodService(uow).get_food(uuid.uuid4())
