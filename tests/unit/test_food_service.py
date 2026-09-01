import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.food_catalog import FoodListingParams, MeasurementUnit
from app.domain.pagination import PaginatedResult
from app.services.food_catalog.food_service import FoodService

pytestmark = pytest.mark.asyncio


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
        food.is_active = True
        food.category = category
        return food

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
