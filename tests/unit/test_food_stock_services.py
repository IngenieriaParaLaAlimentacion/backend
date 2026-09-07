"""Unit tests for the three services that move and read the food stock."""

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.food_catalog import MeasurementUnit
from app.domain.food_intake import FoodIntakeSource
from app.domain.food_outflow import FoodOutflowSource
from app.domain.food_stock import FoodStockListingParams
from app.domain.user import UserActor, UserRole
from app.exceptions.domain_exceptions import FoodNotFoundError, InsufficientStockError
from app.schemas.food_intakes.food_intake_schema import (
    FoodIntakeRequest,
    FoodLineRequest,
)
from app.schemas.food_outflows.food_outflow_schema import FoodOutflowRequest
from app.services.food_intakes.food_intake_service import FoodIntakeService
from app.services.food_outflows.food_outflow_service import FoodOutflowService
from app.services.food_stock.food_stock_service import FoodStockService

pytestmark = pytest.mark.asyncio

ESTABLISHMENT_ID = uuid.uuid4()
RICE_ID = uuid.uuid4()


@pytest.fixture
def actor():
    return UserActor(user_id=uuid.uuid4(), role=UserRole.ADMIN)


@pytest.fixture
def make_food():
    def _make(food_id=RICE_ID, name="Arroz"):
        category = MagicMock()
        category.id = uuid.uuid4()
        category.name = "Cereales"
        food = MagicMock()
        food.id = food_id
        food.name = name
        food.base_unit = MeasurementUnit.KILOGRAMOS
        food.category = category
        return food

    return _make


@pytest.fixture
def make_stored(make_food):
    """A persisted movement, as get_by_id would return it."""

    def _make(**overrides):
        item = MagicMock()
        item.food = make_food()
        item.quantity = Decimal("10.000")
        stored = MagicMock()
        stored.id = uuid.uuid4()
        stored.establishment_id = ESTABLISHMENT_ID
        stored.responsible_id = uuid.uuid4()
        stored.received_at = datetime.now(timezone.utc)
        stored.occurred_at = stored.received_at
        stored.comments = None
        stored.source = FoodIntakeSource.MANUAL
        stored.created_at = stored.received_at
        stored.items = [item]
        for key, value in overrides.items():
            setattr(stored, key, value)
        return stored

    return _make


@pytest.fixture
def uow(make_food, make_stored):
    uow = AsyncMock()
    uow.food_repo.get_by_ids = AsyncMock(return_value=[make_food()])
    uow.food_intake_repo.get_by_id = AsyncMock(return_value=None)
    uow.food_outflow_repo.get_by_id = AsyncMock(return_value=make_stored())
    uow.food_stock_repo.decrease_many = AsyncMock(return_value={RICE_ID})
    return uow


def _intake_request(**overrides) -> FoodIntakeRequest:
    return FoodIntakeRequest(
        establishment_id=ESTABLISHMENT_ID,
        received_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        items=[FoodLineRequest(food_id=RICE_ID, quantity=Decimal("10"))],
        source=FoodIntakeSource.MANUAL,
        **overrides,
    )


def _outflow_request(**overrides) -> FoodOutflowRequest:
    return FoodOutflowRequest(
        establishment_id=ESTABLISHMENT_ID,
        occurred_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        items=[FoodLineRequest(food_id=RICE_ID, quantity=Decimal("4"))],
        source=FoodOutflowSource.MANUAL,
        **overrides,
    )


class TestRegisterIntake:
    async def test_moves_the_balance_in_one_statement(self, uow, actor, make_stored):
        _, created = await FoodIntakeService(uow).register(_intake_request(), actor)

        assert created is True
        uow.food_stock_repo.increase_batch.assert_awaited_once_with(
            establishment_id=ESTABLISHMENT_ID, quantities={RICE_ID: Decimal("10")}
        )
        uow.commit.assert_awaited_once()

    async def test_replay_leaves_the_balance_alone(self, uow, actor, make_stored):
        """Re-applying a re-sent intake would silently inflate the stock."""
        uow.food_intake_repo.get_by_id = AsyncMock(return_value=make_stored())

        _, created = await FoodIntakeService(uow).register(
            _intake_request(id=uuid.uuid4()), actor
        )

        assert created is False
        uow.food_stock_repo.increase_batch.assert_not_awaited()
        uow.commit.assert_not_awaited()

    async def test_unknown_food_raises_before_writing(self, uow, actor):
        uow.food_repo.get_by_ids = AsyncMock(return_value=[])

        with pytest.raises(FoodNotFoundError):
            await FoodIntakeService(uow).register(_intake_request(), actor)

        uow.food_intake_repo.create.assert_not_awaited()
        uow.food_stock_repo.increase_batch.assert_not_awaited()


class TestRegisterOutflow:
    async def test_spends_the_balance(self, uow, actor):
        _, created = await FoodOutflowService(uow).register(_outflow_request(), actor)

        assert created is True
        uow.food_stock_repo.decrease_many.assert_awaited_once_with(
            ESTABLISHMENT_ID, {RICE_ID: Decimal("4")}
        )

    async def test_insufficient_stock_reports_what_is_held(self, uow, actor):
        uow.food_outflow_repo.get_by_id = AsyncMock(return_value=None)
        uow.food_stock_repo.decrease_many = AsyncMock(return_value=set())
        uow.food_stock_repo.get_many = AsyncMock(
            return_value={RICE_ID: Decimal("2.500")}
        )

        with pytest.raises(InsufficientStockError) as error:
            await FoodOutflowService(uow).register(_outflow_request(), actor)

        assert error.value.extensions["available"] == "2.500"
        assert error.value.extensions["requested"] == "4"
        uow.commit.assert_not_awaited()

    async def test_a_food_with_no_balance_row_reports_zero(self, uow, actor):
        uow.food_outflow_repo.get_by_id = AsyncMock(return_value=None)
        uow.food_stock_repo.decrease_many = AsyncMock(return_value=set())
        uow.food_stock_repo.get_many = AsyncMock(return_value={})

        with pytest.raises(InsufficientStockError) as error:
            await FoodOutflowService(uow).register(_outflow_request(), actor)

        assert error.value.extensions["available"] == "0"

    async def test_the_balance_is_only_read_when_the_spend_fails(self, uow, actor):
        """Reading it first would reopen the race the conditional update closes."""
        await FoodOutflowService(uow).register(_outflow_request(), actor)

        uow.food_stock_repo.get_many.assert_not_awaited()


class TestStockListing:
    async def test_computes_the_offset_from_the_page(self, uow, actor):
        uow.food_stock_repo.list_by_establishment = AsyncMock(return_value=([], 0))

        await FoodStockService(uow).list_stock(
            establishment_id=ESTABLISHMENT_ID,
            actor=actor,
            page=3,
            page_size=10,
            params=FoodStockListingParams(),
        )

        _, kwargs = uow.food_stock_repo.list_by_establishment.call_args
        assert kwargs["limit"] == 10
        assert kwargs["offset"] == 20

    async def test_page_zero_is_clamped(self, uow, actor):
        uow.food_stock_repo.list_by_establishment = AsyncMock(return_value=([], 0))

        result = await FoodStockService(uow).list_stock(
            establishment_id=ESTABLISHMENT_ID,
            actor=actor,
            page=0,
            page_size=10,
            params=FoodStockListingParams(),
        )

        assert result.page == 1

    async def test_movements_of_an_unknown_food_raise(self, uow, actor):
        uow.food_repo.get_by_ids = AsyncMock(return_value=[])

        with pytest.raises(FoodNotFoundError):
            await FoodStockService(uow).list_movements(
                establishment_id=ESTABLISHMENT_ID,
                food_id=uuid.uuid4(),
                actor=actor,
                page=1,
                page_size=10,
            )
