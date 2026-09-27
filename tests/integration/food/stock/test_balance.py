import asyncio
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest_asyncio

from tests.integration.food.stock.helpers import (
    _balance,
)


async def _move(establishment_id, food_id, quantity: Decimal, *, up: bool) -> bool:
    """Apply one balance movement in its own committed transaction."""
    from app.db.database import AsyncSessionLocal
    from app.repositories.food_stock.food_stock_repository import FoodStockRepository

    async with AsyncSessionLocal() as session:
        repo = FoodStockRepository(session)
        if up:
            await repo.increase_batch(establishment_id, {food_id: quantity})
            applied = True
        else:
            covered = await repo.decrease_many(establishment_id, {food_id: quantity})
            applied = food_id in covered
        await session.commit()
        return applied


@pytest_asyncio.fixture
async def responsible(app):
    """A field worker to attribute movements to."""
    from app.db.database import AsyncSessionLocal
    from app.domain.user import UserRole, UserStatus
    from app.models.auth.user import User

    async with AsyncSessionLocal() as session:
        user = User(
            name="Lucia",
            last_name="Stock",
            email=f"{uuid.uuid4()}@test.com",
            role=UserRole.FIELD_WORKER,
            status=UserStatus.ACTIVE,
        )
        session.add(user)
        await session.commit()
        return user


async def _persist_intake(establishment_id, responsible_id, items):
    """Persist an intake and move the balance, as the service will."""
    from app.db.database import AsyncSessionLocal
    from app.domain.food_intake import FoodIntakeSource
    from app.models.food_intakes.food_intake import FoodIntake
    from app.models.food_intakes.food_intake_item import FoodIntakeItem
    from app.repositories.food_intakes.food_intake_repository import (
        FoodIntakeRepository,
    )
    from app.repositories.food_stock.food_stock_repository import FoodStockRepository

    async with AsyncSessionLocal() as session:
        intake = FoodIntake(
            establishment_id=establishment_id,
            responsible_id=responsible_id,
            occurred_at=datetime.now(timezone.utc),
            source=FoodIntakeSource.MANUAL,
        )
        intake.items = [
            FoodIntakeItem(food_id=food_id, quantity=quantity)
            for food_id, quantity in items
        ]
        await FoodIntakeRepository(session).create(intake)
        await FoodStockRepository(session).increase_batch(establishment_id, dict(items))
        await session.commit()


async def _persist_outflow(establishment_id, responsible_id, items):
    """Persist an outflow and move the balance, as the service will."""
    from app.db.database import AsyncSessionLocal
    from app.domain.food_outflow import FoodOutflowSource
    from app.models.food_outflows.food_outflow import FoodOutflow
    from app.models.food_outflows.food_outflow_item import FoodOutflowItem
    from app.repositories.food_outflows.food_outflow_repository import (
        FoodOutflowRepository,
    )
    from app.repositories.food_stock.food_stock_repository import FoodStockRepository

    async with AsyncSessionLocal() as session:
        outflow = FoodOutflow(
            establishment_id=establishment_id,
            responsible_id=responsible_id,
            occurred_at=datetime.now(timezone.utc),
            source=FoodOutflowSource.MANUAL,
        )
        outflow.items = [
            FoodOutflowItem(food_id=food_id, quantity=quantity)
            for food_id, quantity in items
        ]
        await FoodOutflowRepository(session).create(outflow)
        covered = await FoodStockRepository(session).decrease_many(
            establishment_id, dict(items)
        )
        assert covered == {food_id for food_id, _ in items}
        await session.commit()


class TestBalanceMovements:
    async def test_first_increase_creates_the_row(
        self, db_establishment, foods
    ) -> None:
        assert await _balance(db_establishment.id, foods.rice) is None

        await _move(db_establishment.id, foods.rice, Decimal("25.5"), up=True)

        assert await _balance(db_establishment.id, foods.rice) == Decimal("25.500")

    async def test_further_increases_accumulate(self, db_establishment, foods) -> None:
        await _move(db_establishment.id, foods.rice, Decimal("10"), up=True)
        await _move(db_establishment.id, foods.rice, Decimal("5.25"), up=True)

        assert await _balance(db_establishment.id, foods.rice) == Decimal("15.250")

    async def test_decrease_subtracts(self, db_establishment, foods) -> None:
        await _move(db_establishment.id, foods.rice, Decimal("10"), up=True)

        assert await _move(db_establishment.id, foods.rice, Decimal("4"), up=False)
        assert await _balance(db_establishment.id, foods.rice) == Decimal("6.000")

    async def test_depleted_food_keeps_a_zero_row(
        self, db_establishment, foods
    ) -> None:
        """Never received and ran out are different answers; keep the row."""
        await _move(db_establishment.id, foods.rice, Decimal("10"), up=True)
        await _move(db_establishment.id, foods.rice, Decimal("10"), up=False)

        assert await _balance(db_establishment.id, foods.rice) == Decimal("0.000")

    async def test_decrease_beyond_the_balance_is_refused(
        self, db_establishment, foods
    ) -> None:
        await _move(db_establishment.id, foods.rice, Decimal("10"), up=True)

        assert not await _move(db_establishment.id, foods.rice, Decimal("11"), up=False)
        assert await _balance(db_establishment.id, foods.rice) == Decimal("10.000")

    async def test_decrease_of_a_never_received_food_is_refused(
        self, db_establishment, foods
    ) -> None:
        assert not await _move(db_establishment.id, foods.eggs, Decimal("1"), up=False)
        assert await _balance(db_establishment.id, foods.eggs) is None

    async def test_balances_are_per_establishment_and_food(
        self, db_establishment, foods, app
    ) -> None:
        from app.db.database import AsyncSessionLocal
        from app.models.establishments.establishment import Establishment

        async with AsyncSessionLocal() as session:
            other = Establishment(
                name="Otro comedor",
                formatted_address="Calle 2",
                latitude=-34.6,
                longitude=-58.4,
                place_id="place-test-002",
                city="Buenos Aires",
                province="Buenos Aires",
            )
            session.add(other)
            await session.commit()
            other_id = other.id

        await _move(db_establishment.id, foods.rice, Decimal("10"), up=True)

        assert await _balance(other_id, foods.rice) is None
        assert await _balance(db_establishment.id, foods.eggs) is None


class TestConcurrency:
    async def test_two_outflows_cannot_overspend_one_balance(
        self, db_establishment, foods
    ) -> None:
        """The guard is inside the UPDATE, so the loser re-reads and fails."""
        await _move(db_establishment.id, foods.rice, Decimal("10"), up=True)

        results = await asyncio.gather(
            _move(db_establishment.id, foods.rice, Decimal("6"), up=False),
            _move(db_establishment.id, foods.rice, Decimal("6"), up=False),
        )

        assert sorted(results) == [False, True]
        assert await _balance(db_establishment.id, foods.rice) == Decimal("4.000")


class TestRecompute:
    async def test_recompute_agrees_with_the_incremental_balance(
        self, db_establishment, responsible, foods
    ) -> None:
        """The materialized balance must equal the sum of what actually moved."""
        from app.db.database import AsyncSessionLocal
        from app.repositories.food_stock.food_stock_repository import (
            FoodStockRepository,
        )

        await _persist_intake(
            db_establishment.id,
            responsible.id,
            [(foods.rice, Decimal("30")), (foods.eggs, Decimal("120"))],
        )
        await _persist_intake(
            db_establishment.id, responsible.id, [(foods.rice, Decimal("12.5"))]
        )
        await _persist_outflow(
            db_establishment.id, responsible.id, [(foods.rice, Decimal("8"))]
        )
        await _persist_outflow(
            db_establishment.id, responsible.id, [(foods.eggs, Decimal("120"))]
        )

        before = {
            foods.rice: await _balance(db_establishment.id, foods.rice),
            foods.eggs: await _balance(db_establishment.id, foods.eggs),
        }
        assert before == {foods.rice: Decimal("34.500"), foods.eggs: Decimal("0.000")}

        async with AsyncSessionLocal() as session:
            await FoodStockRepository(session).recompute(db_establishment.id)
            await session.commit()

        after = {
            foods.rice: await _balance(db_establishment.id, foods.rice),
            foods.eggs: await _balance(db_establishment.id, foods.eggs),
        }
        assert after == before

    async def test_recompute_repairs_a_drifted_balance(
        self, db_establishment, responsible, foods
    ) -> None:
        from app.db.database import AsyncSessionLocal
        from app.repositories.food_stock.food_stock_repository import (
            FoodStockRepository,
        )

        await _persist_intake(
            db_establishment.id, responsible.id, [(foods.rice, Decimal("10"))]
        )
        # Simulate drift: a balance nobody's movements justify.
        await _move(db_establishment.id, foods.rice, Decimal("99"), up=True)

        async with AsyncSessionLocal() as session:
            await FoodStockRepository(session).recompute(db_establishment.id)
            await session.commit()

        assert await _balance(db_establishment.id, foods.rice) == Decimal("10.000")
