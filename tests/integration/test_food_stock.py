"""Integration tests for the materialized per-establishment food stock."""

import asyncio
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio


@dataclass
class Foods:
    rice: UUID  # "Arroz", kilogramos
    eggs: UUID  # "Huevo", unidades


@pytest_asyncio.fixture
async def foods(app) -> Foods:
    """Seed two catalog foods with different base units."""
    from app.db.database import AsyncSessionLocal
    from app.domain.food_catalog import MeasurementUnit
    from app.models.food_catalog.food import Food
    from app.models.food_catalog.food_category import FoodCategory

    async with AsyncSessionLocal() as session:
        cereals = FoodCategory(code="cereales", name="Cereales")
        session.add(cereals)
        await session.flush()

        rice = Food(
            code="arroz",
            name="Arroz",
            category_id=cereals.id,
            base_unit=MeasurementUnit.KILOGRAMOS,
        )
        eggs = Food(
            code="huevo",
            name="Huevo",
            category_id=cereals.id,
            base_unit=MeasurementUnit.UNIDADES,
        )
        session.add_all([rice, eggs])
        await session.commit()
        return Foods(rice=rice.id, eggs=eggs.id)


async def _balance(establishment_id, food_id) -> Decimal | None:
    """Read one balance straight from the table, or None if there is no row."""
    from app.db.database import AsyncSessionLocal
    from app.repositories.food_stock.food_stock_repository import FoodStockRepository

    async with AsyncSessionLocal() as session:
        held = await FoodStockRepository(session).get_many(establishment_id, [food_id])
        return held.get(food_id)


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
            received_at=datetime.now(timezone.utc),
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


# --- HTTP: el slice vertical completo -------------------------------------

INTAKES_URL = "/api/v1/food-intakes"
OUTFLOWS_URL = "/api/v1/food-outflows"


def _stock_url(establishment_id) -> str:
    return f"/api/v1/establishments/{establishment_id}/stock"


def _intake_body(establishment_id, items, **overrides) -> dict:
    body = {
        "establishment_id": str(establishment_id),
        "received_at": "2026-09-01T10:00:00Z",
        "items": [
            {"food_id": str(food_id), "quantity": str(quantity)}
            for food_id, quantity in items
        ],
    }
    return {**body, **overrides}


def _outflow_body(establishment_id, items, **overrides) -> dict:
    body = {
        "establishment_id": str(establishment_id),
        "occurred_at": "2026-09-02T10:00:00Z",
        "items": [
            {"food_id": str(food_id), "quantity": str(quantity)}
            for food_id, quantity in items
        ],
    }
    return {**body, **overrides}


class TestRegisterIntake:
    async def test_intake_creates_the_stock(
        self, client, field_worker_with_access, db_establishment, foods
    ) -> None:
        headers, _ = field_worker_with_access

        response = await client.post(
            INTAKES_URL,
            json=_intake_body(
                db_establishment.id, [(foods.rice, "25.5"), (foods.eggs, "360")]
            ),
            headers=headers,
        )

        assert response.status_code == 201
        body = response.json()
        assert len(body["items"]) == 2
        units = {item["food"]["name"]: item["unit"] for item in body["items"]}
        assert units == {"Arroz": "kilogramos", "Huevo": "unidades"}
        assert await _balance(db_establishment.id, foods.rice) == Decimal("25.500")

    async def test_replayed_intake_does_not_double_the_stock(
        self, client, field_worker_with_access, db_establishment, foods
    ) -> None:
        """The whole point of the replay short-circuit."""
        headers, _ = field_worker_with_access
        body = _intake_body(
            db_establishment.id, [(foods.rice, "10")], id=str(uuid.uuid4())
        )

        first = await client.post(INTAKES_URL, json=body, headers=headers)
        second = await client.post(INTAKES_URL, json=body, headers=headers)

        assert first.status_code == 201
        assert second.status_code == 200
        assert await _balance(db_establishment.id, foods.rice) == Decimal("10.000")

    async def test_repeated_lines_of_one_food_add_up(
        self, client, field_worker_with_access, db_establishment, foods
    ) -> None:
        """Two lines of the same food are their sum, not the last one."""
        headers, _ = field_worker_with_access

        response = await client.post(
            INTAKES_URL,
            json=_intake_body(
                db_establishment.id, [(foods.rice, "10"), (foods.rice, "2.5")]
            ),
            headers=headers,
        )

        assert response.status_code == 201
        assert len(response.json()["items"]) == 2
        assert await _balance(db_establishment.id, foods.rice) == Decimal("12.500")

    async def test_unknown_food_answers_404(
        self, client, field_worker_with_access, db_establishment, foods
    ) -> None:
        headers, _ = field_worker_with_access

        response = await client.post(
            INTAKES_URL,
            json=_intake_body(db_establishment.id, [(uuid.uuid4(), "1")]),
            headers=headers,
        )

        assert response.status_code == 404
        assert response.json()["type"].endswith("food-not-found")

    async def test_field_worker_without_access_is_refused(
        self, client, make_field_worker_with_access, db_establishment, foods, app
    ) -> None:
        from app.db.database import AsyncSessionLocal
        from app.models.establishments.establishment import Establishment

        async with AsyncSessionLocal() as session:
            other = Establishment(
                name="Ajeno",
                formatted_address="Calle 3",
                latitude=-34.6,
                longitude=-58.4,
                place_id="place-test-003",
                city="Buenos Aires",
                province="Buenos Aires",
            )
            session.add(other)
            await session.commit()
            other_id = other.id

        headers, _ = await make_field_worker_with_access(other_id)

        response = await client.post(
            INTAKES_URL,
            json=_intake_body(db_establishment.id, [(foods.rice, "1")]),
            headers=headers,
        )

        assert response.status_code == 403


class TestRegisterOutflow:
    async def test_outflow_subtracts_from_the_stock(
        self, client, field_worker_with_access, db_establishment, foods
    ) -> None:
        headers, _ = field_worker_with_access
        await client.post(
            INTAKES_URL,
            json=_intake_body(db_establishment.id, [(foods.rice, "10")]),
            headers=headers,
        )

        response = await client.post(
            OUTFLOWS_URL,
            json=_outflow_body(db_establishment.id, [(foods.rice, "4")]),
            headers=headers,
        )

        assert response.status_code == 201
        assert await _balance(db_establishment.id, foods.rice) == Decimal("6.000")

    async def test_repeated_lines_of_one_food_are_spent_together(
        self, client, field_worker_with_access, db_establishment, foods
    ) -> None:
        """Folded into one spend, so the balance answers the total once."""
        headers, _ = field_worker_with_access
        await client.post(
            INTAKES_URL,
            json=_intake_body(db_establishment.id, [(foods.rice, "10")]),
            headers=headers,
        )

        response = await client.post(
            OUTFLOWS_URL,
            json=_outflow_body(
                db_establishment.id, [(foods.rice, "7"), (foods.rice, "6")]
            ),
            headers=headers,
        )

        assert response.status_code == 409
        body = response.json()
        assert body["requested"] == "13"
        assert body["available"] == "10.000"
        assert await _balance(db_establishment.id, foods.rice) == Decimal("10.000")

    async def test_outflow_beyond_the_stock_answers_409_and_persists_nothing(
        self, client, field_worker_with_access, db_establishment, foods, app
    ) -> None:
        from sqlalchemy import func, select

        from app.db.database import AsyncSessionLocal
        from app.models.food_outflows.food_outflow import FoodOutflow

        headers, _ = field_worker_with_access
        await client.post(
            INTAKES_URL,
            json=_intake_body(db_establishment.id, [(foods.rice, "10")]),
            headers=headers,
        )

        response = await client.post(
            OUTFLOWS_URL,
            json=_outflow_body(db_establishment.id, [(foods.rice, "11")]),
            headers=headers,
        )

        assert response.status_code == 409
        body = response.json()
        assert body["type"].endswith("insufficient-stock")
        assert body["available"] == "10.000"
        assert body["requested"] == "11"
        assert await _balance(db_establishment.id, foods.rice) == Decimal("10.000")

        async with AsyncSessionLocal() as session:
            count = await session.execute(select(func.count()).select_from(FoodOutflow))
            assert count.scalar_one() == 0

    async def test_a_second_line_failing_rolls_back_the_first(
        self, client, field_worker_with_access, db_establishment, foods
    ) -> None:
        """No half-applied outflow: the covered line must not stick."""
        headers, _ = field_worker_with_access
        await client.post(
            INTAKES_URL,
            json=_intake_body(
                db_establishment.id, [(foods.rice, "10"), (foods.eggs, "5")]
            ),
            headers=headers,
        )

        response = await client.post(
            OUTFLOWS_URL,
            json=_outflow_body(
                db_establishment.id, [(foods.rice, "2"), (foods.eggs, "99")]
            ),
            headers=headers,
        )

        assert response.status_code == 409
        # The covered line is not the one that failed: the error must name eggs.
        assert response.json()["food_id"] == str(foods.eggs)
        assert await _balance(db_establishment.id, foods.rice) == Decimal("10.000")
        assert await _balance(db_establishment.id, foods.eggs) == Decimal("5.000")

    async def test_outflow_of_a_never_received_food_answers_409(
        self, client, field_worker_with_access, db_establishment, foods
    ) -> None:
        headers, _ = field_worker_with_access

        response = await client.post(
            OUTFLOWS_URL,
            json=_outflow_body(db_establishment.id, [(foods.eggs, "1")]),
            headers=headers,
        )

        assert response.status_code == 409
        assert response.json()["available"] == "0"


class TestStockListing:
    async def test_listing_carries_the_catalog_unit_and_category(
        self, client, field_worker_with_access, db_establishment, foods
    ) -> None:
        headers, _ = field_worker_with_access
        await client.post(
            INTAKES_URL,
            json=_intake_body(
                db_establishment.id, [(foods.rice, "10"), (foods.eggs, "12")]
            ),
            headers=headers,
        )

        response = await client.get(_stock_url(db_establishment.id), headers=headers)

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 2
        first = body["items"][0]
        assert first["food"]["name"] == "Arroz"
        assert first["unit"] == "kilogramos"
        assert first["category"]["name"] == "Cereales"
        assert first["quantity"] == "10.000"

    async def test_only_available_hides_depleted_foods(
        self, client, field_worker_with_access, db_establishment, foods
    ) -> None:
        headers, _ = field_worker_with_access
        await client.post(
            INTAKES_URL,
            json=_intake_body(
                db_establishment.id, [(foods.rice, "10"), (foods.eggs, "12")]
            ),
            headers=headers,
        )
        await client.post(
            OUTFLOWS_URL,
            json=_outflow_body(db_establishment.id, [(foods.eggs, "12")]),
            headers=headers,
        )

        everything = await client.get(_stock_url(db_establishment.id), headers=headers)
        available = await client.get(
            _stock_url(db_establishment.id),
            params={"only_available": "true"},
            headers=headers,
        )

        assert everything.json()["total"] == 2
        assert available.json()["total"] == 1
        assert available.json()["items"][0]["food"]["name"] == "Arroz"

    async def test_unknown_establishment_answers_404(
        self, client, admin_headers
    ) -> None:
        response = await client.get(_stock_url(uuid.uuid4()), headers=admin_headers)

        assert response.status_code == 404

    async def test_field_worker_without_access_is_refused(
        self, client, make_field_worker_with_access, db_establishment, app
    ) -> None:
        from app.db.database import AsyncSessionLocal
        from app.models.establishments.establishment import Establishment

        async with AsyncSessionLocal() as session:
            other = Establishment(
                name="Ajeno",
                formatted_address="Calle 4",
                latitude=-34.6,
                longitude=-58.4,
                place_id="place-test-004",
                city="Buenos Aires",
                province="Buenos Aires",
            )
            session.add(other)
            await session.commit()
            other_id = other.id

        headers, _ = await make_field_worker_with_access(other_id)

        response = await client.get(_stock_url(db_establishment.id), headers=headers)

        assert response.status_code == 403

    async def test_unauthenticated_is_refused(self, client, db_establishment) -> None:
        response = await client.get(_stock_url(db_establishment.id))

        assert response.status_code == 401


class TestMovements:
    async def test_movements_merge_both_directions_newest_first(
        self, client, field_worker_with_access, db_establishment, foods
    ) -> None:
        headers, _ = field_worker_with_access
        await client.post(
            INTAKES_URL,
            json=_intake_body(db_establishment.id, [(foods.rice, "10")]),
            headers=headers,
        )
        await client.post(
            OUTFLOWS_URL,
            json=_outflow_body(
                db_establishment.id, [(foods.rice, "4")], comments="Almuerzo"
            ),
            headers=headers,
        )

        response = await client.get(
            f"{_stock_url(db_establishment.id)}/{foods.rice}/movements",
            headers=headers,
        )

        assert response.status_code == 200
        items = response.json()["items"]
        assert [item["direction"] for item in items] == ["out", "in"]
        assert items[0]["quantity"] == "4.000"
        assert items[0]["comments"] == "Almuerzo"

    async def test_unknown_food_answers_404(
        self, client, field_worker_with_access, db_establishment
    ) -> None:
        headers, _ = field_worker_with_access

        response = await client.get(
            f"{_stock_url(db_establishment.id)}/{uuid.uuid4()}/movements",
            headers=headers,
        )

        assert response.status_code == 404


class TestStockExport:
    async def test_export_row_count_matches_the_file(
        self, client, field_worker_with_access, db_establishment, foods
    ) -> None:
        headers, _ = field_worker_with_access
        await client.post(
            INTAKES_URL,
            json=_intake_body(
                db_establishment.id, [(foods.rice, "10.5"), (foods.eggs, "12")]
            ),
            headers=headers,
        )

        response = await client.get(
            f"{_stock_url(db_establishment.id)}/export", headers=headers
        )

        assert response.status_code == 200
        assert response.headers["X-Export-Row-Count"] == "2"
        lines = response.text.strip().splitlines()
        assert len(lines) == 3  # header + 2 rows
        assert "Alimento" in lines[0]
        assert "10,500" in response.text
