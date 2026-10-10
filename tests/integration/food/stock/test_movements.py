import uuid

import pytest

from tests.integration.food.stock.helpers import (
    INTAKES_URL,
    OUTFLOWS_URL,
    _intake_body,
    _outflow_body,
)


def _movements_url(establishment_id) -> str:
    return f"/api/v1/establishments/{establishment_id}/food-movements"


def _movement_detail_url(establishment_id, movement_id) -> str:
    return f"{_movements_url(establishment_id)}/{movement_id}"


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
        assert items[0]["origin_type"] is None
        assert items[0]["is_recurring"] is None
        assert items[1]["origin_type"] == "other"
        assert items[1]["is_recurring"] is False

    async def test_an_entry_is_the_summary_shape(
        self, client, field_worker_with_access, db_establishment, foods
    ) -> None:
        """A listing row carries intake facts but no establishment, lines, source
        or comments."""
        headers, user_id = field_worker_with_access
        # Posted with comments so the key set proves they are withheld.
        await client.post(
            INTAKES_URL,
            json=_intake_body(
                db_establishment.id,
                [(foods.rice, "10")],
                comments="Donación",
                origin_type="foundation",
                is_recurring=True,
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
            "origin_type",
            "is_recurring",
        }
        assert item["origin_type"] == "foundation"
        assert item["is_recurring"] is True
        assert set(item["responsible"]) == {"id", "name", "last_name"}
        assert item["responsible"]["id"] == str(user_id)
        # `occurred_at` as sent: the event date, not when the row was written.
        assert item["occurred_at"] == "2026-09-01T10:00:00Z"

    async def test_the_food_filter_keeps_only_movements_carrying_it(
        self, client, field_worker_with_access, db_establishment, foods
    ) -> None:
        headers, _ = field_worker_with_access
        with_rice = await client.post(
            INTAKES_URL,
            json=_intake_body(db_establishment.id, [(foods.rice, "10")]),
            headers=headers,
        )
        await client.post(
            INTAKES_URL,
            json=_intake_body(db_establishment.id, [(foods.eggs, "12")]),
            headers=headers,
        )

        response = await client.get(
            _movements_url(db_establishment.id),
            params={"food_id": str(foods.rice)},
            headers=headers,
        )

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert [item["id"] for item in body["items"]] == [with_rice.json()["id"]]

    async def test_a_movement_repeating_the_food_is_listed_once(
        self, client, field_worker_with_access, db_establishment, foods
    ) -> None:
        """A join to the line table would return it twice and count it twice."""
        headers, _ = field_worker_with_access
        await client.post(
            INTAKES_URL,
            json=_intake_body(
                db_establishment.id, [(foods.rice, "2"), (foods.rice, "3")]
            ),
            headers=headers,
        )

        response = await client.get(
            _movements_url(db_establishment.id),
            params={"food_id": str(foods.rice)},
            headers=headers,
        )

        body = response.json()
        assert body["total"] == 1
        assert len(body["items"]) == 1

    async def test_the_food_filter_reaches_the_total_not_just_the_page(
        self, client, field_worker_with_access, db_establishment, foods
    ) -> None:
        """`total` is counted over the filtered set, so a paged client is not
        told there are more movements than the filter admits."""
        headers, _ = field_worker_with_access
        for _ in range(2):
            await client.post(
                INTAKES_URL,
                json=_intake_body(db_establishment.id, [(foods.rice, "10")]),
                headers=headers,
            )
        await client.post(
            INTAKES_URL,
            json=_intake_body(db_establishment.id, [(foods.eggs, "12")]),
            headers=headers,
        )

        response = await client.get(
            _movements_url(db_establishment.id),
            params={"food_id": str(foods.rice), "page_size": 1},
            headers=headers,
        )

        body = response.json()
        assert len(body["items"]) == 1
        assert body["total"] == 2
        assert body["total_pages"] == 2

    async def test_an_unknown_food_is_an_empty_page(
        self, client, field_worker_with_access, db_establishment, foods
    ) -> None:
        """A filter, not a resource: filtering by something absent matches
        nothing rather than answering 404."""
        headers, _ = field_worker_with_access
        await client.post(
            INTAKES_URL,
            json=_intake_body(db_establishment.id, [(foods.rice, "10")]),
            headers=headers,
        )

        response = await client.get(
            _movements_url(db_establishment.id),
            params={"food_id": str(uuid.uuid4())},
            headers=headers,
        )

        assert response.status_code == 200
        assert response.json()["items"] == []
        assert response.json()["total"] == 0

    async def test_the_food_filter_combines_with_direction(
        self, client, field_worker_with_access, db_establishment, foods
    ) -> None:
        headers, _ = field_worker_with_access
        await client.post(
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
            _movements_url(db_establishment.id),
            params={"food_id": str(foods.rice), "direction": "out"},
            headers=headers,
        )

        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["id"] == outflow.json()["id"]

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
        self,
        client,
        make_field_worker_with_access,
        db_establishment,
        foods,
        other_establishment_id,
    ) -> None:
        """The establishment filter lives inside each union branch; a branch
        missing it would leak here and nowhere else."""
        mine_headers, _ = await make_field_worker_with_access(db_establishment.id)
        other_headers, _ = await make_field_worker_with_access(other_establishment_id)
        my_intake = await client.post(
            INTAKES_URL,
            json=_intake_body(db_establishment.id, [(foods.rice, "10")]),
            headers=mine_headers,
        )
        their_intake = await client.post(
            INTAKES_URL,
            json=_intake_body(other_establishment_id, [(foods.eggs, "6")]),
            headers=other_headers,
        )

        mine = await client.get(
            _movements_url(db_establishment.id), headers=mine_headers
        )
        theirs = await client.get(
            _movements_url(other_establishment_id), headers=other_headers
        )

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
        self,
        client,
        make_field_worker_with_access,
        db_establishment,
        other_establishment_id,
    ) -> None:
        headers, _ = await make_field_worker_with_access(other_establishment_id)

        response = await client.get(
            _movements_url(db_establishment.id), headers=headers
        )

        assert response.status_code == 403

    async def test_unauthenticated_is_refused(self, client, db_establishment) -> None:
        response = await client.get(_movements_url(db_establishment.id))

        assert response.status_code == 401


class TestMovementDetail:
    async def test_an_intake_detail_carries_its_lines(
        self, client, field_worker_with_access, db_establishment, foods
    ) -> None:
        headers, user_id = field_worker_with_access
        intake = await client.post(
            INTAKES_URL,
            json=_intake_body(
                db_establishment.id,
                [(foods.rice, "2.5"), (foods.eggs, "12")],
                comments="Donación",
            ),
            headers=headers,
        )

        response = await client.get(
            _movement_detail_url(db_establishment.id, intake.json()["id"]),
            headers=headers,
        )

        assert response.status_code == 200
        body = response.json()
        assert set(body) == {
            "id",
            "direction",
            "occurred_at",
            "source",
            "origin_type",
            "is_recurring",
            "comments",
            "responsible",
            "items",
        }
        assert body["direction"] == "in"
        assert body["source"] == "manual"
        assert body["origin_type"] == "other"
        assert body["is_recurring"] is False
        assert body["comments"] == "Donación"
        assert body["responsible"]["id"] == str(user_id)
        assert set(body["responsible"]) == {"id", "name", "last_name"}
        assert {
            (line["food"]["name"], line["unit"], line["quantity"])
            for line in body["items"]
        } == {
            ("Arroz", "kilogramos", "2.500"),
            ("Huevo", "unidades", "12.000"),
        }

    async def test_an_outflow_detail_has_the_same_shape(
        self, client, field_worker_with_access, db_establishment, foods
    ) -> None:
        """Source and comments are exposed on both directions, not just intakes."""
        headers, _ = field_worker_with_access
        await client.post(
            INTAKES_URL,
            json=_intake_body(db_establishment.id, [(foods.rice, "10")]),
            headers=headers,
        )
        outflow = await client.post(
            OUTFLOWS_URL,
            json=_outflow_body(
                db_establishment.id, [(foods.rice, "4")], comments="Almuerzo"
            ),
            headers=headers,
        )

        response = await client.get(
            _movement_detail_url(db_establishment.id, outflow.json()["id"]),
            headers=headers,
        )

        assert response.status_code == 200
        body = response.json()
        assert body["direction"] == "out"
        assert body["source"] == "manual"
        assert body["origin_type"] is None
        assert body["is_recurring"] is None
        assert body["comments"] == "Almuerzo"
        assert [line["quantity"] for line in body["items"]] == ["4.000"]

    async def test_repeated_food_lines_are_returned_as_recorded(
        self, client, field_worker_with_access, db_establishment, foods
    ) -> None:
        """The counterpart of the listing's distinct `food_count`: the detail
        never aggregates."""
        headers, _ = field_worker_with_access
        intake = await client.post(
            INTAKES_URL,
            json=_intake_body(
                db_establishment.id, [(foods.rice, "2"), (foods.rice, "3")]
            ),
            headers=headers,
        )

        response = await client.get(
            _movement_detail_url(db_establishment.id, intake.json()["id"]),
            headers=headers,
        )

        lines = response.json()["items"]
        assert len(lines) == 2
        assert sorted(line["quantity"] for line in lines) == ["2.000", "3.000"]

    async def test_a_movement_of_another_establishment_is_not_found(
        self,
        client,
        make_field_worker_with_access,
        db_establishment,
        foods,
        other_establishment_id,
    ) -> None:
        """404, not 403: a 403 would confirm the id exists somewhere else."""
        mine_headers, _ = await make_field_worker_with_access(db_establishment.id)
        other_headers, _ = await make_field_worker_with_access(other_establishment_id)
        intake = await client.post(
            INTAKES_URL,
            json=_intake_body(db_establishment.id, [(foods.rice, "10")]),
            headers=mine_headers,
        )

        response = await client.get(
            _movement_detail_url(other_establishment_id, intake.json()["id"]),
            headers=other_headers,
        )

        assert response.status_code == 404

    async def test_an_unknown_movement_is_not_found(
        self, client, field_worker_with_access, db_establishment
    ) -> None:
        headers, _ = field_worker_with_access

        response = await client.get(
            _movement_detail_url(db_establishment.id, uuid.uuid4()), headers=headers
        )

        assert response.status_code == 404
        assert response.json()["type"] == "/errors/food-movement-not-found"

    async def test_an_unknown_establishment_is_not_found(
        self, client, admin_headers
    ) -> None:
        response = await client.get(
            _movement_detail_url(uuid.uuid4(), uuid.uuid4()), headers=admin_headers
        )

        assert response.status_code == 404

    async def test_a_field_worker_without_access_is_refused(
        self,
        client,
        make_field_worker_with_access,
        db_establishment,
        foods,
        other_establishment_id,
    ) -> None:
        mine_headers, _ = await make_field_worker_with_access(db_establishment.id)
        outsider_headers, _ = await make_field_worker_with_access(
            other_establishment_id
        )
        intake = await client.post(
            INTAKES_URL,
            json=_intake_body(db_establishment.id, [(foods.rice, "10")]),
            headers=mine_headers,
        )

        response = await client.get(
            _movement_detail_url(db_establishment.id, intake.json()["id"]),
            headers=outsider_headers,
        )

        assert response.status_code == 403

    async def test_unauthenticated_is_refused(self, client, db_establishment) -> None:
        response = await client.get(
            _movement_detail_url(db_establishment.id, uuid.uuid4())
        )

        assert response.status_code == 401
