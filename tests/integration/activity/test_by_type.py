from decimal import Decimal

from fastapi import status

from tests.integration.activity.helpers import (
    ACTIVITY_URL,
    _create_food_intake,
    _create_food_outflow,
    _create_survey,
    _submit_survey_response,
)

MOVEMENT_PAYLOAD_KEYS = {
    "id",
    "occurred_at",
    "establishment",
    "source",
    "origin_type",
    "is_recurring",
    "comments",
    "items",
}


class TestSurveyResponseActivity:
    async def test_numberless_response_appears_with_null_number(
        self, client, db_establishment, field_worker_a, survey_author
    ):
        headers, _ = field_worker_a
        survey = await _create_survey(client, survey_author)
        await _submit_survey_response(
            client,
            headers,
            survey,
            "2024-01-01T00:00:00Z",
            response_number=None,
        )

        response = await client.get(ACTIVITY_URL, headers=headers)

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["items"][0]["survey_response"]["response_number"] is None

    async def test_submitted_response_appears_for_submitter(
        self, client, db_establishment, field_worker_a, survey_author
    ):
        headers, _ = field_worker_a
        survey = await _create_survey(client, survey_author)
        response_id = await _submit_survey_response(
            client, headers, survey, "2024-01-01T00:00:00Z"
        )

        response = await client.get(ACTIVITY_URL, headers=headers)
        body = response.json()
        assert body["total"] == 1
        item = body["items"][0]
        assert item["type"] == "survey_response"
        assert item["survey_response"]["id"] == response_id
        # An anonymous response has no target at all. The feed must render it
        # rather than blow up dereferencing a missing establishment.
        assert item["survey_response"]["establishment"] is None
        assert item["survey_response"]["subject"] is None

    async def test_subject_targeted_response_carries_the_subject(
        self, client, field_worker_a, survey_author, db_subject
    ):
        headers, _ = field_worker_a
        survey = await _create_survey(client, survey_author, response_target="subject")
        await _submit_survey_response(
            client,
            headers,
            survey,
            "2024-01-01T00:00:00Z",
            subject_id=str(db_subject.id),
        )

        response = await client.get(ACTIVITY_URL, headers=headers)
        item = response.json()["items"][0]
        assert item["survey_response"]["subject"]["id"] == str(db_subject.id)
        assert item["survey_response"]["subject"]["dni"] == db_subject.dni
        assert item["survey_response"]["establishment"] is None

    async def test_does_not_leak_to_other_submitters(
        self, client, db_establishment, field_worker_a, field_worker_b, survey_author
    ):
        headers_a, _ = field_worker_a
        headers_b, _ = field_worker_b
        survey = await _create_survey(client, survey_author)
        await _submit_survey_response(client, headers_a, survey, "2024-01-01T00:00:00Z")

        response_b = await client.get(ACTIVITY_URL, headers=headers_b)
        assert response_b.json()["total"] == 0


class TestFoodIntakeActivity:
    async def test_intake_appears_in_unfiltered_feed(
        self, client, db_establishment, field_worker_a, foods
    ):
        headers, _ = field_worker_a
        intake_id = await _create_food_intake(
            client,
            headers,
            db_establishment.id,
            "2024-04-01T00:00:00Z",
            [(foods.rice, "2.500")],
        )

        response = await client.get(ACTIVITY_URL, headers=headers)

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["total"] == 1
        item = body["items"][0]
        assert item["type"] == "food_intake"
        assert item["food_intake"]["id"] == intake_id
        assert item["food_intake"]["origin_type"] == "other"
        assert item["food_intake"]["is_recurring"] is False
        # Additive contract: the opposite direction stays null.
        assert item["food_outflow"] is None

    async def test_intake_payload_carries_lines_units_and_establishment(
        self, client, db_establishment, field_worker_a, foods
    ):
        headers, _ = field_worker_a
        await _create_food_intake(
            client,
            headers,
            db_establishment.id,
            "2024-04-01T00:00:00Z",
            [(foods.rice, "2.500"), (foods.eggs, "12")],
            origin_type="church",
            is_recurring=True,
        )

        body = (await client.get(ACTIVITY_URL, headers=headers)).json()
        payload = body["items"][0]["food_intake"]

        # occurred_at is normalized to the shared occurred_at.
        assert payload["occurred_at"] == "2024-04-01T00:00:00Z"
        assert set(payload) == MOVEMENT_PAYLOAD_KEYS
        assert set(payload["establishment"]) == {"id", "name", "city", "province"}
        assert payload["establishment"]["id"] == str(db_establishment.id)
        assert payload["establishment"]["name"] == db_establishment.name
        assert payload["source"] == "manual"
        assert payload["origin_type"] == "church"
        assert payload["is_recurring"] is True
        assert payload["comments"] is None

        lines = payload["items"]
        assert len(lines) == 2
        # The unit comes from each line's own food, not from a constant.
        assert {(line["food"]["name"], line["unit"]) for line in lines} == {
            ("Arroz", "kilogramos"),
            ("Huevo", "unidades"),
        }
        by_name = {line["food"]["name"]: line for line in lines}
        assert by_name["Arroz"]["food"]["id"] == str(foods.rice)
        assert by_name["Huevo"]["food"]["id"] == str(foods.eggs)
        # numeric(10,3) round-trips as 2.5 or 2.500 depending on serialization;
        # only the numeric value is contractual.
        assert Decimal(str(by_name["Arroz"]["quantity"])) == Decimal("2.500")
        assert Decimal(str(by_name["Huevo"]["quantity"])) == Decimal("12")

    async def test_duplicate_food_lines_render_verbatim(
        self, client, db_establishment, field_worker_a, foods
    ):
        """The same food may appear twice on one intake: there is no unique
        (food_intake_id, food_id). The read path renders both lines as stored
        and never aggregates them into a single summed line."""
        headers, _ = field_worker_a
        await _create_food_intake(
            client,
            headers,
            db_establishment.id,
            "2024-04-01T00:00:00Z",
            [(foods.rice, "1.000"), (foods.rice, "2.000")],
        )

        body = (await client.get(ACTIVITY_URL, headers=headers)).json()
        lines = body["items"][0]["food_intake"]["items"]

        assert len(lines) == 2
        assert [line["food"]["name"] for line in lines] == ["Arroz", "Arroz"]
        assert [Decimal(str(line["quantity"])) for line in lines] == [
            Decimal("1.000"),
            Decimal("2.000"),
        ]

    async def test_intake_does_not_leak_to_another_user(
        self, client, db_establishment, field_worker_a, field_worker_b, foods
    ):
        """Access to the establishment is not access to someone else's feed."""
        headers_a, _ = field_worker_a
        headers_b, _ = field_worker_b
        await _create_food_intake(
            client,
            headers_a,
            db_establishment.id,
            "2024-04-01T00:00:00Z",
            [(foods.rice, "2.500")],
        )

        body_b = (await client.get(ACTIVITY_URL, headers=headers_b)).json()

        assert body_b["total"] == 0
        assert body_b["items"] == []

    async def test_comments_and_photo_source_round_trip(
        self, client, db_establishment, field_worker_a, foods
    ):
        headers, _ = field_worker_a
        await _create_food_intake(
            client,
            headers,
            db_establishment.id,
            "2024-04-01T00:00:00Z",
            [(foods.rice, "2.500")],
            comments="Donación parroquia",
            source="photo",
        )

        body = (await client.get(ACTIVITY_URL, headers=headers)).json()
        payload = body["items"][0]["food_intake"]

        assert payload["comments"] == "Donación parroquia"
        assert payload["source"] == "photo"


class TestFoodOutflowActivity:
    async def test_outflow_appears_in_unfiltered_feed(
        self, client, db_establishment, field_worker_a, foods
    ):
        headers, _ = field_worker_a
        # Outflows spend stock, so the intake below is what makes them possible.
        await _create_food_intake(
            client,
            headers,
            db_establishment.id,
            "2024-04-01T00:00:00Z",
            [(foods.rice, "5.000")],
        )
        outflow_id = await _create_food_outflow(
            client,
            headers,
            db_establishment.id,
            "2024-05-01T00:00:00Z",
            [(foods.rice, "1.000")],
        )

        body = (await client.get(ACTIVITY_URL, headers=headers)).json()

        assert body["total"] == 2
        item = body["items"][0]
        assert item["type"] == "food_outflow"
        assert item["food_outflow"]["id"] == outflow_id
        assert item["food_outflow"]["origin_type"] is None
        assert item["food_outflow"]["is_recurring"] is None
        assert item["food_intake"] is None

    async def test_outflow_payload_normalizes_occurred_at(
        self, client, db_establishment, field_worker_a, foods
    ):
        headers, _ = field_worker_a
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

        body = (
            await client.get(
                ACTIVITY_URL, params={"type": "food_outflow"}, headers=headers
            )
        ).json()
        payload = body["items"][0]["food_outflow"]

        assert payload["occurred_at"] == "2024-05-01T00:00:00Z"
        # One shared schema serves both directions.
        assert set(payload) == MOVEMENT_PAYLOAD_KEYS
        assert payload["establishment"]["id"] == str(db_establishment.id)
        assert payload["source"] == "manual"
        assert payload["comments"] is None
        assert [line["unit"] for line in payload["items"]] == ["kilogramos"]

    async def test_outflow_does_not_leak_to_another_user(
        self, client, db_establishment, field_worker_a, field_worker_b, foods
    ):
        headers_a, _ = field_worker_a
        headers_b, _ = field_worker_b
        await _create_food_intake(
            client,
            headers_a,
            db_establishment.id,
            "2024-04-01T00:00:00Z",
            [(foods.rice, "5.000")],
        )
        await _create_food_outflow(
            client,
            headers_a,
            db_establishment.id,
            "2024-05-01T00:00:00Z",
            [(foods.rice, "1.000")],
        )

        body_b = (await client.get(ACTIVITY_URL, headers=headers_b)).json()

        assert body_b["total"] == 0
        assert body_b["items"] == []
