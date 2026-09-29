import uuid

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

SIBLING_KEYS = (
    "subject",
    "measurement",
    "survey_response",
    "food_intake",
    "food_outflow",
)


def _populated_siblings(item):
    return [key for key in SIBLING_KEYS if item[key] is not None]


class TestAuth:
    async def test_unauthenticated_returns_401(self, client):
        response = await client.get(ACTIVITY_URL)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_admin_with_no_activity_returns_empty_feed(
        self, client, admin_headers
    ):
        response = await client.get(ACTIVITY_URL, headers=admin_headers)
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {
            "items": [],
            "total": 0,
            "page": 1,
            "page_size": 20,
            "total_pages": 0,
        }


class TestMergedFeed:
    async def test_returns_subject_and_measurements_ordered_desc(
        self, client, db_establishment, field_worker_a
    ):
        headers, _ = field_worker_a
        subject_id = await _create_subject(client, headers, dni=11111111)
        m_early = await _create_measurement(
            client,
            headers,
            subject_id,
            db_establishment.id,
            "2024-01-01T00:00:00Z",
        )
        m_late = await _create_measurement(
            client,
            headers,
            subject_id,
            db_establishment.id,
            "2024-06-01T00:00:00Z",
        )

        response = await client.get(ACTIVITY_URL, headers=headers)
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["total"] == 3

        items = body["items"]
        assert [i["type"] for i in items] == ["subject", "measurement", "measurement"]
        assert items[0]["subject"]["id"] == subject_id
        assert items[1]["measurement"]["id"] == m_late
        assert items[2]["measurement"]["id"] == m_early

    async def test_second_field_worker_activity_does_not_leak(
        self, client, db_establishment, field_worker_a, field_worker_b
    ):
        headers_a, _ = field_worker_a
        headers_b, _ = field_worker_b

        subject_a = await _create_subject(client, headers_a, dni=22222221)
        measurement_a = await _create_measurement(
            client, headers_a, subject_a, db_establishment.id, "2024-01-01T00:00:00Z"
        )

        subject_b = await _create_subject(client, headers_b, dni=22222222)

        response_a = await client.get(ACTIVITY_URL, headers=headers_a)
        body_a = response_a.json()
        assert body_a["total"] == 2
        assert {i["type"] for i in body_a["items"]} == {"subject", "measurement"}
        subject_item_a = next(i for i in body_a["items"] if i["type"] == "subject")
        measurement_item_a = next(
            i for i in body_a["items"] if i["type"] == "measurement"
        )
        assert subject_item_a["subject"]["id"] == subject_a
        assert measurement_item_a["measurement"]["id"] == measurement_a

        response_b = await client.get(ACTIVITY_URL, headers=headers_b)
        body_b = response_b.json()
        assert body_b["total"] == 1
        assert body_b["items"][0]["subject"]["id"] == subject_b


class TestTypeFilter:
    async def test_type_subject_returns_only_subject_item(
        self, client, db_establishment, field_worker_a
    ):
        headers, _ = field_worker_a
        subject_id = await _create_subject(client, headers, dni=33333331)
        await _create_measurement(
            client, headers, subject_id, db_establishment.id, "2024-01-01T00:00:00Z"
        )

        response = await client.get(
            ACTIVITY_URL, params={"type": "subject"}, headers=headers
        )
        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["type"] == "subject"
        assert body["items"][0]["subject"]["id"] == subject_id

    async def test_type_measurement_returns_only_measurement_items(
        self, client, db_establishment, field_worker_a
    ):
        headers, _ = field_worker_a
        subject_id = await _create_subject(client, headers, dni=33333332)
        m1 = await _create_measurement(
            client, headers, subject_id, db_establishment.id, "2024-01-01T00:00:00Z"
        )
        m2 = await _create_measurement(
            client, headers, subject_id, db_establishment.id, "2024-06-01T00:00:00Z"
        )

        response = await client.get(
            ACTIVITY_URL, params={"type": "measurement"}, headers=headers
        )
        body = response.json()
        assert body["total"] == 2
        assert all(i["type"] == "measurement" for i in body["items"])
        assert {i["measurement"]["id"] for i in body["items"]} == {m1, m2}

    async def test_type_survey_response_returns_only_survey_response_items(
        self, client, db_establishment, field_worker_a, survey_author
    ):
        headers, _ = field_worker_a
        survey = await _create_survey(client, survey_author)
        response_id = await _submit_survey_response(
            client, headers, survey, "2024-01-01T00:00:00Z"
        )

        response = await client.get(
            ACTIVITY_URL, params={"type": "survey_response"}, headers=headers
        )
        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["type"] == "survey_response"
        assert body["items"][0]["survey_response"]["id"] == response_id
        assert body["items"][0]["survey_response"]["survey"]["id"] == survey["id"]


class TestPagination:
    async def test_tied_timestamps_paginate_without_duplicates_or_gaps(
        self, client, db_establishment, field_worker_a
    ):
        """Three measurements sharing the same measured_at rely on the id DESC
        tiebreak to paginate deterministically."""
        headers, _ = field_worker_a
        subject_id = await _create_subject(client, headers, dni=44444441)

        ids = [uuid.uuid4() for _ in range(3)]
        for measurement_id in ids:
            await _create_measurement(
                client,
                headers,
                subject_id,
                db_establishment.id,
                "2024-03-01T00:00:00Z",
                id=str(measurement_id),
            )
        expected_order = [str(i) for i in sorted(ids, reverse=True)]

        page_1 = await client.get(
            ACTIVITY_URL,
            params={"page": 1, "page_size": 2, "type": "measurement"},
            headers=headers,
        )
        page_2 = await client.get(
            ACTIVITY_URL,
            params={"page": 2, "page_size": 2, "type": "measurement"},
            headers=headers,
        )

        body_1 = page_1.json()
        body_2 = page_2.json()
        assert body_1["total"] == 3
        assert body_1["total_pages"] == 2
        assert len(body_1["items"]) == 2
        assert len(body_2["items"]) == 1

        returned_ids = [i["measurement"]["id"] for i in body_1["items"]] + [
            i["measurement"]["id"] for i in body_2["items"]
        ]
        assert returned_ids == expected_order
        assert len(set(returned_ids)) == 3


class TestActivityItemTagging:
    async def test_every_type_in_a_mixed_feed_tags_its_own_sibling(
        self, client, db_establishment, field_worker_a, survey_author, foods
    ):
        """The same contract over a feed containing every type at once."""
        headers, _ = field_worker_a
        subject_id = await _create_subject(client, headers, dni=88888881)
        await _create_measurement(
            client, headers, subject_id, db_establishment.id, "2024-02-01T00:00:00Z"
        )
        survey = await _create_survey(client, survey_author)
        await _submit_survey_response(client, headers, survey, "2024-03-01T00:00:00Z")
        await _create_food_intake(
            client,
            headers,
            db_establishment.id,
            "2024-04-01T00:00:00Z",
            [(foods.rice, "5.000")],
        )
        await _create_food_outflow(
            client,
            headers,
            db_establishment.id,
            "2024-05-01T00:00:00Z",
            [(foods.rice, "1.000")],
        )

        body = (await client.get(ACTIVITY_URL, headers=headers)).json()

        assert len(body["items"]) == 5
        for item in body["items"]:
            assert _populated_siblings(item) == [item["type"]]
