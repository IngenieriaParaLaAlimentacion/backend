import uuid
from decimal import Decimal

import pytest

from tests.integration.food.stock.helpers import (
    INTAKES_URL,
    OUTFLOWS_URL,
    _balance,
    _intake_body,
    _outflow_body,
)


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
        self,
        client,
        make_field_worker_with_access,
        db_establishment,
        foods,
        other_establishment_id,
    ) -> None:
        headers, _ = await make_field_worker_with_access(other_establishment_id)

        response = await client.post(
            INTAKES_URL,
            json=_intake_body(db_establishment.id, [(foods.rice, "1")]),
            headers=headers,
        )

        assert response.status_code == 403


class TestRegisterOutflow:
    @pytest.mark.parametrize(
        "category", ["family_delivery", "kitchen", "discard", "other"]
    )
    async def test_each_category_is_stored_and_returned(
        self, client, field_worker_with_access, db_establishment, foods, category
    ) -> None:
        headers, _ = field_worker_with_access
        await client.post(
            INTAKES_URL,
            json=_intake_body(db_establishment.id, [(foods.rice, "10")]),
            headers=headers,
        )

        response = await client.post(
            OUTFLOWS_URL,
            json=_outflow_body(
                db_establishment.id, [(foods.rice, "4")], category=category
            ),
            headers=headers,
        )

        assert response.status_code == 201
        assert response.json()["category"] == category
        assert await _balance(db_establishment.id, foods.rice) == Decimal("6.000")

    async def test_legacy_omission_records_other_and_keeps_comments(
        self, client, field_worker_with_access, db_establishment, foods
    ) -> None:
        headers, _ = field_worker_with_access
        await client.post(
            INTAKES_URL,
            json=_intake_body(db_establishment.id, [(foods.rice, "10")]),
            headers=headers,
        )
        body = _outflow_body(
            db_establishment.id, [(foods.rice, "1")], comments="Legacy detail"
        )
        del body["category"]

        response = await client.post(OUTFLOWS_URL, json=body, headers=headers)

        assert response.status_code == 201
        assert response.json()["category"] == "other"
        assert response.json()["comments"] == "Legacy detail"

    @pytest.mark.parametrize("comments", [None, "", "unexpected"])
    async def test_non_other_rejects_any_comments_key_without_spending(
        self, client, field_worker_with_access, db_establishment, foods, comments
    ) -> None:
        headers, _ = field_worker_with_access
        await client.post(
            INTAKES_URL,
            json=_intake_body(db_establishment.id, [(foods.rice, "10")]),
            headers=headers,
        )

        response = await client.post(
            OUTFLOWS_URL,
            json=_outflow_body(
                db_establishment.id,
                [(foods.rice, "4")],
                category="kitchen",
                comments=comments,
            ),
            headers=headers,
        )

        assert response.status_code == 422
        assert response.json()["type"] == "/errors/validation-failed"
        assert await _balance(db_establishment.id, foods.rice) == Decimal("10.000")

    @pytest.mark.parametrize("category", [None, "unknown"])
    async def test_invalid_category_is_rejected_without_spending(
        self, client, field_worker_with_access, db_establishment, foods, category
    ) -> None:
        headers, _ = field_worker_with_access
        await client.post(
            INTAKES_URL,
            json=_intake_body(db_establishment.id, [(foods.rice, "10")]),
            headers=headers,
        )

        response = await client.post(
            OUTFLOWS_URL,
            json=_outflow_body(
                db_establishment.id, [(foods.rice, "4")], category=category
            ),
            headers=headers,
        )

        assert response.status_code == 422
        assert response.json()["type"] == "/errors/validation-failed"
        assert await _balance(db_establishment.id, foods.rice) == Decimal("10.000")

    async def test_replay_keeps_original_category_and_balance(
        self, client, field_worker_with_access, db_establishment, foods
    ) -> None:
        headers, _ = field_worker_with_access
        await client.post(
            INTAKES_URL,
            json=_intake_body(db_establishment.id, [(foods.rice, "10")]),
            headers=headers,
        )
        outflow_id = str(uuid.uuid4())
        original = _outflow_body(
            db_establishment.id,
            [(foods.rice, "4")],
            id=outflow_id,
            category="kitchen",
        )

        first = await client.post(OUTFLOWS_URL, json=original, headers=headers)
        retry = await client.post(
            OUTFLOWS_URL,
            json={**original, "category": "discard"},
            headers=headers,
        )

        assert first.status_code == 201
        assert retry.status_code == 200
        assert retry.json()["category"] == "kitchen"
        assert await _balance(db_establishment.id, foods.rice) == Decimal("6.000")

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
