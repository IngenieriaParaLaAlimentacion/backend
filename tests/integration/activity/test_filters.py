import uuid

import pytest
from fastapi import status

from tests.integration.activity.helpers import (
    ACTIVITY_URL,
    _create_food_intake,
    _create_food_outflow,
    _create_measurement,
    _create_subject,
    _create_survey,
    _submit_survey_response,
)


def _item_id(item):
    """Read the id from whichever sibling payload this item populates."""
    payload = item[item["type"]]
    return payload["id"]


class TestFoodMovementTypeFilter:
    @pytest.mark.parametrize("movement", ["food_intake", "food_outflow"])
    async def test_food_type_returns_only_that_movement(
        self, client, db_establishment, field_worker_a, foods, movement
    ):
        headers, _ = field_worker_a
        subject_id = await _create_subject(client, headers, dni=66666661)
        await _create_measurement(
            client, headers, subject_id, db_establishment.id, "2024-02-01T00:00:00Z"
        )
        # The intake comes first: the outflow spends its stock.
        created = {
            "food_intake": await _create_food_intake(
                client,
                headers,
                db_establishment.id,
                "2024-04-01T00:00:00Z",
                [(foods.rice, "5.000")],
            ),
            "food_outflow": await _create_food_outflow(
                client,
                headers,
                db_establishment.id,
                "2024-05-01T00:00:00Z",
                [(foods.rice, "1.000")],
            ),
        }

        body = (
            await client.get(ACTIVITY_URL, params={"type": movement}, headers=headers)
        ).json()

        assert body["total"] == 1
        assert all(i["type"] == movement for i in body["items"])
        assert body["items"][0][movement]["id"] == created[movement]


class TestMultiTypeFilter:
    """A repeated `type` yields one merged, correctly-paginated feed."""

    async def _seed_two_direction_feed(
        self, client, headers, establishment_id, foods, dni
    ):
        """Seed four interleaved food movements plus one subject and one
        measurement, so "and nothing else" is a meaningful assertion.

        The first intake covers the stock every outflow draws down, so the
        movements can then be dated in any order.
        """
        intake_a = await _create_food_intake(
            client,
            headers,
            establishment_id,
            "2024-04-01T00:00:00Z",
            [(foods.rice, "10.000")],
        )
        outflow_1 = await _create_food_outflow(
            client,
            headers,
            establishment_id,
            "2024-03-01T00:00:00Z",
            [(foods.rice, "1.000")],
        )
        intake_b = await _create_food_intake(
            client,
            headers,
            establishment_id,
            "2024-02-01T00:00:00Z",
            [(foods.rice, "1.000")],
        )
        outflow_2 = await _create_food_outflow(
            client,
            headers,
            establishment_id,
            "2024-01-01T00:00:00Z",
            [(foods.rice, "1.000")],
        )

        subject_id = await _create_subject(client, headers, dni=dni)
        await _create_measurement(
            client, headers, subject_id, establishment_id, "2024-07-01T00:00:00Z"
        )
        return [intake_a, outflow_1, intake_b, outflow_2]

    async def test_two_types_return_one_merged_feed(
        self, client, db_establishment, field_worker_a, foods
    ):
        headers, _ = field_worker_a
        expected_order = await self._seed_two_direction_feed(
            client, headers, db_establishment.id, foods, dni=77777771
        )

        body = (
            await client.get(
                ACTIVITY_URL,
                params={"type": ["food_intake", "food_outflow"]},
                headers=headers,
            )
        ).json()

        assert body["total"] == 4
        assert all(i["type"] in {"food_intake", "food_outflow"} for i in body["items"])
        assert [_item_id(i) for i in body["items"]] == expected_order

    async def test_duplicate_type_is_idempotent(
        self, client, db_establishment, field_worker_a
    ):
        """An un-deduped duplicate branch silently doubles the rows AND the
        total, so both are asserted against the single-value baseline."""
        headers, _ = field_worker_a
        await _create_subject(client, headers, dni=77777772)

        single = (
            await client.get(ACTIVITY_URL, params={"type": "subject"}, headers=headers)
        ).json()
        duplicated = (
            await client.get(
                ACTIVITY_URL, params={"type": ["subject", "subject"]}, headers=headers
            )
        ).json()

        assert duplicated["total"] == single["total"] == 1
        assert [_item_id(i) for i in duplicated["items"]] == [
            _item_id(i) for i in single["items"]
        ]

    async def test_total_equals_the_sum_of_the_single_type_totals(
        self, client, db_establishment, field_worker_a
    ):
        headers, _ = field_worker_a
        subject_id = await _create_subject(client, headers, dni=77777773)
        await _create_measurement(
            client, headers, subject_id, db_establishment.id, "2024-01-01T00:00:00Z"
        )
        await _create_measurement(
            client, headers, subject_id, db_establishment.id, "2024-06-01T00:00:00Z"
        )

        subjects = (
            await client.get(ACTIVITY_URL, params={"type": "subject"}, headers=headers)
        ).json()
        measurements = (
            await client.get(
                ACTIVITY_URL, params={"type": "measurement"}, headers=headers
            )
        ).json()
        merged = (
            await client.get(
                ACTIVITY_URL,
                params={"type": ["subject", "measurement"]},
                headers=headers,
            )
        ).json()

        assert merged["total"] == subjects["total"] + measurements["total"] == 3

    async def test_request_order_does_not_change_the_result(
        self, client, db_establishment, field_worker_a, foods
    ):
        headers, _ = field_worker_a
        await self._seed_two_direction_feed(
            client, headers, db_establishment.id, foods, dni=77777775
        )

        forward = (
            await client.get(
                ACTIVITY_URL,
                params={"type": ["food_intake", "food_outflow"]},
                headers=headers,
            )
        ).json()
        reversed_ = (
            await client.get(
                ACTIVITY_URL,
                params={"type": ["food_outflow", "food_intake"]},
                headers=headers,
            )
        ).json()

        assert reversed_["total"] == forward["total"]
        assert [_item_id(i) for i in reversed_["items"]] == [
            _item_id(i) for i in forward["items"]
        ]

    async def test_all_five_types_requested_equals_the_unfiltered_feed(
        self, client, db_establishment, field_worker_a, foods
    ):
        headers, _ = field_worker_a
        await self._seed_two_direction_feed(
            client, headers, db_establishment.id, foods, dni=77777776
        )

        every_type = (
            await client.get(
                ACTIVITY_URL,
                params={
                    "type": [
                        "subject",
                        "measurement",
                        "survey_response",
                        "food_intake",
                        "food_outflow",
                    ]
                },
                headers=headers,
            )
        ).json()
        unfiltered = (await client.get(ACTIVITY_URL, headers=headers)).json()

        assert every_type["total"] == unfiltered["total"] == 6
        assert [_item_id(i) for i in every_type["items"]] == [
            _item_id(i) for i in unfiltered["items"]
        ]

    async def test_pagination_across_a_two_type_feed_neither_skips_nor_repeats(
        self, client, db_establishment, field_worker_a, foods
    ):
        headers, _ = field_worker_a
        expected = await self._seed_two_direction_feed(
            client, headers, db_establishment.id, foods, dni=77777778
        )

        walked = []
        for page in (1, 2):
            body = (
                await client.get(
                    ACTIVITY_URL,
                    params={
                        "page": page,
                        "page_size": 2,
                        "type": ["food_intake", "food_outflow"],
                    },
                    headers=headers,
                )
            ).json()
            assert body["total"] == 4
            assert body["total_pages"] == 2
            assert len(body["items"]) == 2
            walked += [_item_id(i) for i in body["items"]]

        assert walked == expected
        assert len(set(walked)) == 4


class TestMultiTypeFilterRejections:
    @pytest.mark.parametrize(
        "params",
        [
            {"type": ""},
            {"type": "bogus"},
            {"type": ["subject", "bogus"]},
            {"type": "subject,food_intake"},
        ],
        ids=["empty", "unknown", "one-good-one-bad", "comma-separated"],
    )
    async def test_invalid_type_values_are_rejected_with_422(
        self, client, field_worker_a, params
    ):
        """Widening `type` to a list must not degrade it into a free-form
        string param: no empty value, no unknown value, no partial acceptance
        and no comma-separated form."""
        headers, _ = field_worker_a

        response = await client.get(ACTIVITY_URL, params=params, headers=headers)

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


class TestMixedFeedWithFoodMovements:
    async def _seed_five_row_feed(
        self, client, headers, survey_author, establishment_id, foods, dni
    ):
        """A subject, a measurement, a survey response, an intake and an
        outflow — exactly five rows, the intake doubling as the outflow's
        stock."""
        subject_id = await _create_subject(client, headers, dni=dni)
        await _create_measurement(
            client, headers, subject_id, establishment_id, "2024-02-01T00:00:00Z"
        )
        survey = await _create_survey(client, survey_author)
        await _submit_survey_response(client, headers, survey, "2024-03-01T00:00:00Z")
        await _create_food_intake(
            client,
            headers,
            establishment_id,
            "2024-04-01T00:00:00Z",
            [(foods.rice, "5.000")],
        )
        await _create_food_outflow(
            client,
            headers,
            establishment_id,
            "2024-05-01T00:00:00Z",
            [(foods.rice, "1.000")],
        )

    async def test_five_types_interleave_by_occurred_at_desc(
        self, client, db_establishment, field_worker_a, survey_author, foods
    ):
        headers, _ = field_worker_a
        await self._seed_five_row_feed(
            client, headers, survey_author, db_establishment.id, foods, 77777771
        )

        body = (await client.get(ACTIVITY_URL, headers=headers)).json()

        assert body["total"] == 5
        # subject's occurred_at is server-generated "now" (via subject_events),
        # so it sorts ahead of the client-dated 2024 rows.
        assert [i["type"] for i in body["items"]] == [
            "subject",
            "food_outflow",
            "food_intake",
            "survey_response",
            "measurement",
        ]

    async def test_total_and_total_pages_widen_with_food_movements(
        self, client, db_establishment, field_worker_a, survey_author, foods
    ):
        """total comes from one COUNT(*) over the same union the page reads, so
        the new branches widen it without total and items ever disagreeing."""
        headers, _ = field_worker_a
        await self._seed_five_row_feed(
            client, headers, survey_author, db_establishment.id, foods, 77777772
        )

        body = (
            await client.get(
                ACTIVITY_URL, params={"page": 1, "page_size": 2}, headers=headers
            )
        ).json()

        assert body["total"] == 5
        assert body["total_pages"] == 3
        assert len(body["items"]) == 2

    async def test_pagination_across_mixed_feed_neither_skips_nor_repeats(
        self, client, db_establishment, field_worker_a, survey_author, foods
    ):
        headers, _ = field_worker_a
        await self._seed_five_row_feed(
            client, headers, survey_author, db_establishment.id, foods, 77777773
        )

        paged_ids = []
        for page in (1, 2, 3):
            body = (
                await client.get(
                    ACTIVITY_URL,
                    params={"page": page, "page_size": 2},
                    headers=headers,
                )
            ).json()
            paged_ids.extend(_item_id(i) for i in body["items"])

        single_page = (
            await client.get(
                ACTIVITY_URL, params={"page": 1, "page_size": 20}, headers=headers
            )
        ).json()
        expected_ids = [_item_id(i) for i in single_page["items"]]

        assert len(set(paged_ids)) == 5
        assert paged_ids == expected_ids

    async def test_tied_timestamps_across_intake_and_outflow(
        self, client, db_establishment, field_worker_a, foods
    ):
        """The occurred_at DESC, id DESC tiebreak has to hold across branches,
        not just within one — a per-branch ORDER BY would get this wrong."""
        headers, _ = field_worker_a
        intake_id = uuid.uuid4()
        outflow_id = uuid.uuid4()
        await _create_food_intake(
            client,
            headers,
            db_establishment.id,
            "2024-04-01T00:00:00Z",
            [(foods.rice, "5.000")],
            id=str(intake_id),
        )
        await _create_food_outflow(
            client,
            headers,
            db_establishment.id,
            "2024-04-01T00:00:00Z",
            [(foods.rice, "1.000")],
            id=str(outflow_id),
        )
        expected_order = [str(i) for i in sorted([intake_id, outflow_id], reverse=True)]

        returned_ids = []
        for page in (1, 2):
            body = (
                await client.get(
                    ACTIVITY_URL,
                    params={"page": page, "page_size": 1},
                    headers=headers,
                )
            ).json()
            assert body["total"] == 2
            assert body["total_pages"] == 2
            assert len(body["items"]) == 1
            returned_ids.append(_item_id(body["items"][0]))

        assert returned_ids == expected_order
