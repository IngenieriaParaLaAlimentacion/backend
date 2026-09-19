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


TIED_FOOD_COUNT = 7


@pytest_asyncio.fixture
async def tied_stock(db_establishment) -> list[str]:
    """Seed TIED_FOOD_COUNT foods whose balances all sit at exactly 0.000.

    Insertion order is uncorrelated with the random uuid4 primary keys, so an
    unordered scan almost certainly returns these rows in some order other than
    id order -- without that, a missing tiebreaker would pass by luck.

    Returns the food ids in stock-id order: the sequence the tiebreaker dictates.
    """
    from sqlalchemy import select

    from app.db.database import AsyncSessionLocal
    from app.domain.food_catalog import MeasurementUnit
    from app.models.food_catalog.food import Food
    from app.models.food_catalog.food_category import FoodCategory
    from app.models.food_stock.food_stock import FoodStock
    from app.repositories.food_stock.food_stock_repository import FoodStockRepository

    async with AsyncSessionLocal() as session:
        category = FoodCategory(code="varios", name="Varios")
        session.add(category)
        await session.flush()

        created = [
            Food(
                code=f"tied-{index}",
                name=f"Alimento {index}",
                category_id=category.id,
                base_unit=MeasurementUnit.KILOGRAMOS,
            )
            for index in range(TIED_FOOD_COUNT)
        ]
        session.add_all(created)
        await session.flush()

        # A depleted food keeps a zero row; seeding straight to zero is the
        # same end state an intake followed by a matching outflow reaches.
        await FoodStockRepository(session).increase_batch(
            db_establishment.id, {food.id: Decimal("0") for food in created}
        )
        await session.commit()

        # increase_batch generates the stock ids internally and does not return
        # them, so read them back -- ordered by Postgres, whose uuid comparison
        # is the one the tiebreaker will use.
        rows = await session.execute(
            select(FoodStock.food_id)
            .where(FoodStock.establishment_id == db_establishment.id)
            .order_by(FoodStock.id)
        )
        return [str(food_id) for food_id in rows.scalars()]


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


# --- HTTP: el slice vertical completo -------------------------------------

INTAKES_URL = "/api/v1/food-intakes"
OUTFLOWS_URL = "/api/v1/food-outflows"


def _stock_url(establishment_id) -> str:
    return f"/api/v1/establishments/{establishment_id}/stock"


def _movements_url(establishment_id) -> str:
    return f"/api/v1/establishments/{establishment_id}/food-movements"


async def _walk_stock_pages(
    client, headers, establishment_id, sort_order, page_size: int = 4
) -> list[dict]:
    """Return the items of every page of a stock listing, in page order.

    The page size is deliberately smaller than the seeded row count, so the
    concatenation crosses at least one page boundary -- the only place an
    unresolved sort tie can duplicate or drop a row.
    """
    items: list[dict] = []
    page = 1
    while True:
        response = await client.get(
            _stock_url(establishment_id),
            params={
                "sort_order": sort_order,
                "page": page,
                "page_size": page_size,
            },
            headers=headers,
        )
        assert response.status_code == 200
        body = response.json()
        assert body["total_pages"] > 1, "page_size is too large to cross a boundary"
        items.extend(body["items"])
        if page >= body["total_pages"]:
            return items
        page += 1


def _intake_body(establishment_id, items, **overrides) -> dict:
    body = {
        "establishment_id": str(establishment_id),
        "occurred_at": "2026-09-01T10:00:00Z",
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

    async def test_tied_quantities_paginate_without_duplicates_or_gaps(
        self, client, field_worker_with_access, db_establishment, tied_stock
    ) -> None:
        """Every depleted food is exactly 0.000, so quantity_asc ties en masse.

        With an unresolved tie, LIMIT/OFFSET may hand the same row to two pages
        and never hand over another. An infinite-scroll client would show one
        food twice and lose a different one entirely.
        """
        headers, _ = field_worker_with_access

        items = await _walk_stock_pages(
            client, headers, db_establishment.id, "quantity_asc"
        )

        assert {item["quantity"] for item in items} == {"0.000"}, "nothing tied"
        seen = [item["food"]["id"] for item in items]
        assert len(set(seen)) == TIED_FOOD_COUNT, "a food was duplicated or skipped"
        assert seen == tied_stock, "pages are not ordered by the id tiebreaker"

    async def test_a_single_intake_ties_updated_at_and_still_paginates_cleanly(
        self, client, field_worker_with_access, db_establishment, tied_stock
    ) -> None:
        """One batched intake writes the same now() to every row it touched."""
        headers, _ = field_worker_with_access

        items = await _walk_stock_pages(
            client, headers, db_establishment.id, "updated_at_desc"
        )

        assert len({item["updated_at"] for item in items}) == 1, "nothing tied"
        seen = [item["food"]["id"] for item in items]
        assert len(set(seen)) == TIED_FOOD_COUNT, "a food was duplicated or skipped"
        assert seen == tied_stock, "pages are not ordered by the id tiebreaker"

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
    async def test_a_movement_is_one_entry_counting_its_foods(
        self, client, field_worker_with_access, db_establishment, foods
    ) -> None:
        """A remito with two foods is one entry reporting two, not two entries."""
        headers, _ = field_worker_with_access
        await client.post(
            INTAKES_URL,
            json=_intake_body(
                db_establishment.id, [(foods.rice, "2.5"), (foods.eggs, "12")]
            ),
            headers=headers,
        )

        response = await client.get(
            _movements_url(db_establishment.id), headers=headers
        )

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert len(body["items"]) == 1
        assert body["items"][0]["food_count"] == 2

    async def test_the_same_food_on_two_lines_counts_once(
        self, client, field_worker_with_access, db_establishment, foods
    ) -> None:
        """The same food on two lines counts once: `food_count` is distinct."""
        headers, _ = field_worker_with_access
        await client.post(
            INTAKES_URL,
            json=_intake_body(
                db_establishment.id, [(foods.rice, "2"), (foods.rice, "3")]
            ),
            headers=headers,
        )

        response = await client.get(
            _movements_url(db_establishment.id), headers=headers
        )

        assert response.json()["items"][0]["food_count"] == 1

    async def test_an_outflow_counts_its_own_lines(
        self, client, field_worker_with_access, db_establishment, foods
    ) -> None:
        """An outflow's `food_count` reads the outflow line table."""
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
            json=_outflow_body(
                db_establishment.id, [(foods.rice, "4"), (foods.eggs, "2")]
            ),
            headers=headers,
        )

        response = await client.get(
            _movements_url(db_establishment.id),
            params={"direction": "out"},
            headers=headers,
        )

        assert response.json()["items"][0]["food_count"] == 2

    async def test_each_movement_counts_only_its_own_foods(
        self, client, field_worker_with_access, db_establishment, foods
    ) -> None:
        """Each row counts its own foods, not the establishment's total."""
        headers, _ = field_worker_with_access
        await client.post(
            INTAKES_URL,
            json=_intake_body(
                db_establishment.id,
                [(foods.rice, "10")],
                occurred_at="2026-09-01T10:00:00Z",
            ),
            headers=headers,
        )
        await client.post(
            INTAKES_URL,
            json=_intake_body(
                db_establishment.id,
                [(foods.rice, "5"), (foods.eggs, "12")],
                occurred_at="2026-09-02T10:00:00Z",
            ),
            headers=headers,
        )

        response = await client.get(
            _movements_url(db_establishment.id), headers=headers
        )

        assert [item["food_count"] for item in response.json()["items"]] == [2, 1]

    async def test_each_movement_carries_its_own_responsible(
        self, client, make_field_worker_with_access, db_establishment, foods
    ) -> None:
        """Each row's responsible is the author of that movement."""
        first_headers, first_id = await make_field_worker_with_access(
            db_establishment.id
        )
        second_headers, second_id = await make_field_worker_with_access(
            db_establishment.id
        )
        await client.post(
            INTAKES_URL,
            json=_intake_body(db_establishment.id, [(foods.rice, "10")]),
            headers=first_headers,
        )
        await client.post(
            OUTFLOWS_URL,
            json=_outflow_body(db_establishment.id, [(foods.rice, "4")]),
            headers=second_headers,
        )

        response = await client.get(
            _movements_url(db_establishment.id), headers=first_headers
        )

        items = response.json()["items"]
        assert [item["responsible"]["id"] for item in items] == [
            str(second_id),
            str(first_id),
        ]

    async def test_both_directions_merge_newest_first(
        self, client, field_worker_with_access, db_establishment, foods
    ) -> None:
        headers, _ = field_worker_with_access
        intake = await client.post(
            INTAKES_URL,
            json=_intake_body(db_establishment.id, [(foods.rice, "10")]),
            headers=headers,
        )
        outflow = await client.post(
            OUTFLOWS_URL,
            json=_outflow_body(db_establishment.id, [(foods.rice, "4")]),
            headers=headers,
        )

        response = await client.get(
            _movements_url(db_establishment.id), headers=headers
        )

        assert response.status_code == 200
        items = response.json()["items"]
        assert [item["direction"] for item in items] == ["out", "in"]
        assert [item["id"] for item in items] == [
            outflow.json()["id"],
            intake.json()["id"],
        ]

    async def test_an_entry_is_the_summary_shape(
        self, client, field_worker_with_access, db_establishment, foods
    ) -> None:
        """A listing row carries five keys: no establishment, lines, source
        or comments."""
        headers, user_id = field_worker_with_access
        # Posted with comments so the key set proves they are withheld.
        await client.post(
            INTAKES_URL,
            json=_intake_body(
                db_establishment.id, [(foods.rice, "10")], comments="Donación"
            ),
            headers=headers,
        )

        response = await client.get(
            _movements_url(db_establishment.id), headers=headers
        )

        item = response.json()["items"][0]
        assert set(item) == {
            "id",
            "direction",
            "occurred_at",
            "responsible",
            "food_count",
        }
        assert set(item["responsible"]) == {"id", "name", "last_name"}
        assert item["responsible"]["id"] == str(user_id)
        # `occurred_at` as sent: the event date, not when the row was written.
        assert item["occurred_at"] == "2026-09-01T10:00:00Z"

    @pytest.mark.parametrize("direction", ["in", "out"])
    async def test_the_direction_filter_keeps_one_side(
        self, client, field_worker_with_access, db_establishment, foods, direction
    ) -> None:
        headers, _ = field_worker_with_access
        await client.post(
            INTAKES_URL,
            json=_intake_body(db_establishment.id, [(foods.rice, "10")]),
            headers=headers,
        )
        await client.post(
            OUTFLOWS_URL,
            json=_outflow_body(db_establishment.id, [(foods.rice, "4")]),
            headers=headers,
        )

        response = await client.get(
            _movements_url(db_establishment.id),
            params={"direction": direction},
            headers=headers,
        )

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert [item["direction"] for item in body["items"]] == [direction]

    async def test_the_date_range_reads_the_event_date_not_the_load_date(
        self, client, field_worker_with_access, db_establishment, foods
    ) -> None:
        """Both rows are written now; only their event dates differ. Filtering
        on `created_at` would return both, or neither."""
        headers, _ = field_worker_with_access
        await client.post(
            INTAKES_URL,
            json=_intake_body(
                db_establishment.id,
                [(foods.rice, "10")],
                occurred_at="2026-08-15T10:00:00Z",
            ),
            headers=headers,
        )
        await client.post(
            OUTFLOWS_URL,
            json=_outflow_body(db_establishment.id, [(foods.rice, "4")]),
            headers=headers,
        )

        response = await client.get(
            _movements_url(db_establishment.id),
            params={
                "occurred_from": "2026-08-01T00:00:00Z",
                "occurred_to": "2026-08-31T23:59:59Z",
            },
            headers=headers,
        )

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["direction"] == "in"

    async def test_an_inverted_date_range_is_refused(
        self, client, field_worker_with_access, db_establishment
    ) -> None:
        headers, _ = field_worker_with_access

        response = await client.get(
            _movements_url(db_establishment.id),
            params={
                "occurred_from": "2026-09-30T00:00:00Z",
                "occurred_to": "2026-09-01T00:00:00Z",
            },
            headers=headers,
        )

        assert response.status_code == 400
        assert response.json()["type"] == "/errors/invalid-date-range"

    async def test_paginating_a_timestamp_tie_repeats_nothing(
        self, client, field_worker_with_access, db_establishment, foods
    ) -> None:
        """Every document shares one instant, and the ids come from two tables:
        without the `id` tiebreaker a page repeats a row and drops another."""
        headers, _ = field_worker_with_access
        for _ in range(6):
            await client.post(
                INTAKES_URL,
                json=_intake_body(db_establishment.id, [(foods.rice, "10")]),
                headers=headers,
            )
        for _ in range(6):
            await client.post(
                OUTFLOWS_URL,
                json=_outflow_body(
                    db_establishment.id,
                    [(foods.rice, "1")],
                    occurred_at="2026-09-01T10:00:00Z",
                ),
                headers=headers,
            )

        seen: list[str] = []
        page = 1
        while True:
            response = await client.get(
                _movements_url(db_establishment.id),
                params={"page": page, "page_size": 5},
                headers=headers,
            )
            assert response.status_code == 200
            body = response.json()
            assert body["total"] == 12
            assert body["total_pages"] > 1, "page_size is too large to cross a boundary"
            seen.extend(item["id"] for item in body["items"])
            if page >= body["total_pages"]:
                break
            page += 1

        assert len(seen) == 12
        assert len(set(seen)) == 12

    async def test_another_establishments_movements_are_not_listed(
        self, client, make_field_worker_with_access, db_establishment, foods, app
    ) -> None:
        """The establishment filter lives inside each union branch; a branch
        missing it would leak here and nowhere else."""
        from app.db.database import AsyncSessionLocal
        from app.models.establishments.establishment import Establishment

        async with AsyncSessionLocal() as session:
            other = Establishment(
                name="Ajeno",
                formatted_address="Calle 5",
                latitude=-34.6,
                longitude=-58.4,
                place_id="place-test-005",
                city="Buenos Aires",
                province="Buenos Aires",
            )
            session.add(other)
            await session.commit()
            other_id = other.id

        mine_headers, _ = await make_field_worker_with_access(db_establishment.id)
        other_headers, _ = await make_field_worker_with_access(other_id)
        my_intake = await client.post(
            INTAKES_URL,
            json=_intake_body(db_establishment.id, [(foods.rice, "10")]),
            headers=mine_headers,
        )
        their_intake = await client.post(
            INTAKES_URL,
            json=_intake_body(other_id, [(foods.eggs, "6")]),
            headers=other_headers,
        )

        mine = await client.get(
            _movements_url(db_establishment.id), headers=mine_headers
        )
        theirs = await client.get(_movements_url(other_id), headers=other_headers)

        assert mine.json()["total"] == 1
        assert theirs.json()["total"] == 1
        assert mine.json()["items"][0]["id"] == my_intake.json()["id"]
        assert theirs.json()["items"][0]["id"] == their_intake.json()["id"]

    async def test_no_movements_is_an_empty_page_not_a_404(
        self, client, field_worker_with_access, db_establishment
    ) -> None:
        headers, _ = field_worker_with_access

        response = await client.get(
            _movements_url(db_establishment.id), headers=headers
        )

        assert response.status_code == 200
        body = response.json()
        assert body["items"] == []
        assert body["total"] == 0
        assert body["total_pages"] == 0

    async def test_an_unknown_establishment_is_not_found(
        self, client, admin_headers
    ) -> None:
        response = await client.get(_movements_url(uuid.uuid4()), headers=admin_headers)

        assert response.status_code == 404

    async def test_a_field_worker_without_access_is_refused(
        self, client, make_field_worker_with_access, db_establishment, app
    ) -> None:
        from app.db.database import AsyncSessionLocal
        from app.models.establishments.establishment import Establishment

        async with AsyncSessionLocal() as session:
            other = Establishment(
                name="Ajeno",
                formatted_address="Calle 6",
                latitude=-34.6,
                longitude=-58.4,
                place_id="place-test-006",
                city="Buenos Aires",
                province="Buenos Aires",
            )
            session.add(other)
            await session.commit()
            other_id = other.id

        headers, _ = await make_field_worker_with_access(other_id)

        response = await client.get(
            _movements_url(db_establishment.id), headers=headers
        )

        assert response.status_code == 403

    async def test_unauthenticated_is_refused(self, client, db_establishment) -> None:
        response = await client.get(_movements_url(db_establishment.id))

        assert response.status_code == 401


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
