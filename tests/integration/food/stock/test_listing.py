import uuid
from decimal import Decimal

import pytest_asyncio

from tests.integration.food.stock.helpers import (
    INTAKES_URL,
    OUTFLOWS_URL,
    _intake_body,
    _outflow_body,
)

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


def _stock_url(establishment_id) -> str:
    return f"/api/v1/establishments/{establishment_id}/stock"


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
