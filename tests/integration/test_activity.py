import uuid
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

import pytest
import pytest_asyncio
from fastapi import status

from app.core.security import create_access_token
from app.domain.user import UserRole

pytestmark = pytest.mark.asyncio

ACTIVITY_URL = "/api/v1/users/me/activity"
SUBJECTS_URL = "/api/v1/subjects"
MEASUREMENTS_URL = "/api/v1/measurements"
SURVEYS_URL = "/api/v1/surveys"
FOOD_INTAKES_URL = "/api/v1/food-intakes"
FOOD_OUTFLOWS_URL = "/api/v1/food-outflows"

MOVEMENT_PAYLOAD_KEYS = {
    "id",
    "occurred_at",
    "establishment",
    "source",
    "comments",
    "items",
}
SIBLING_KEYS = (
    "subject",
    "measurement",
    "survey_response",
    "food_intake",
    "food_outflow",
)


def _responses_url(survey_id, *parts):
    segments = [SURVEYS_URL, str(survey_id), "responses"] + [str(p) for p in parts]
    return "/".join(segments)


@pytest_asyncio.fixture
async def field_worker_a(app, db_establishment, make_field_worker_with_access):
    return await make_field_worker_with_access(db_establishment.id)


@pytest_asyncio.fixture
async def field_worker_b(app, db_establishment, make_field_worker_with_access):
    return await make_field_worker_with_access(db_establishment.id)


@pytest_asyncio.fixture
async def survey_author(app):
    """Create a real DB admin user (surveys.created_by_id is a real FK)."""
    from app.db.database import AsyncSessionLocal
    from app.domain.user import UserStatus
    from app.models.auth.user import User
    from app.models.auth.user import UserRole as ORMUserRole

    user_id = uuid.uuid4()
    async with AsyncSessionLocal() as session:
        session.add(
            User(
                id=user_id,
                name="Author",
                last_name="Admin",
                email=f"{user_id}@test.com",
                role=ORMUserRole.ADMIN,
                status=UserStatus.ACTIVE,
            )
        )
        await session.commit()
    token = create_access_token(user_id, role=UserRole.ADMIN)
    return {"Authorization": f"Bearer {token}"}


@dataclass
class Foods:
    rice: UUID  # "Arroz", kilogramos
    eggs: UUID  # "Huevo", unidades


@pytest_asyncio.fixture
async def foods(app) -> Foods:
    """Seed two catalog foods with different base units.

    The catalog has no create endpoint — it is only ever populated by the seed
    script — so the rows go in directly. Two different base_units on purpose:
    the payload's `unit` must come from each line's own food, not from a
    constant.
    """
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


def _movement_body(establishment_id, lines, **overrides):
    return {
        "id": str(uuid.uuid4()),
        "establishment_id": str(establishment_id),
        "comments": None,
        "source": "manual",
        "items": [
            {"food_id": str(food_id), "quantity": str(quantity)}
            for food_id, quantity in lines
        ],
        **overrides,
    }


async def _create_food_intake(
    client, headers, establishment_id, occurred_at, lines, **overrides
):
    body = _movement_body(establishment_id, lines, occurred_at=occurred_at, **overrides)
    response = await client.post(FOOD_INTAKES_URL, json=body, headers=headers)
    assert response.status_code == status.HTTP_201_CREATED
    return response.json()["id"]


async def _create_food_outflow(
    client, headers, establishment_id, occurred_at, lines, **overrides
):
    """Register an outflow.

    Outflows draw down stock and answer 409 /errors/insufficient-stock on an
    insufficient balance, so every caller must register an intake covering the
    same foods first.
    """
    body = _movement_body(establishment_id, lines, occurred_at=occurred_at, **overrides)
    response = await client.post(FOOD_OUTFLOWS_URL, json=body, headers=headers)
    assert response.status_code == status.HTTP_201_CREATED
    return response.json()["id"]


def _populated_siblings(item):
    return [key for key in SIBLING_KEYS if item[key] is not None]


def _item_id(item):
    """Read the id from whichever sibling payload this item populates."""
    payload = item[item["type"]]
    return payload["id"]


def _subject_body(dni: int, **overrides):
    return {
        "dni": dni,
        "sex": "male",
        "name": "Juan",
        "last_name": "Perez",
        "birth_date": "2010-01-01",
        "is_rural": False,
        "is_indigenous": False,
        **overrides,
    }


async def _create_subject(client, headers, dni: int, **overrides):
    response = await client.post(
        SUBJECTS_URL, json=_subject_body(dni, **overrides), headers=headers
    )
    assert response.status_code == status.HTTP_201_CREATED
    return response.json()["id"]


def _measurement_body(subject_id, establishment_id, measured_at, **overrides):
    return {
        "subject_id": str(subject_id),
        "establishment_id": str(establishment_id),
        "weight_kg": 70.0,
        "height_cm": 170.0,
        "measured_at": measured_at,
        **overrides,
    }


async def _create_measurement(
    client, headers, subject_id, establishment_id, measured_at, **overrides
):
    response = await client.post(
        MEASUREMENTS_URL,
        json=_measurement_body(subject_id, establishment_id, measured_at, **overrides),
        headers=headers,
    )
    assert response.status_code == status.HTTP_201_CREATED
    return response.json()["id"]


async def _create_survey(
    client,
    author_headers,
    name: str = "Encuesta A",
    response_target: str = "anonymous",
):
    body = {
        "name": name,
        "description": None,
        "response_target": response_target,
        "questions": [
            {
                "text": "¿Comió hoy?",
                "response_type": "single_choice",
                "is_required": True,
                "options": [{"text": "Sí"}, {"text": "No"}],
            }
        ],
    }
    response = await client.post(SURVEYS_URL, json=body, headers=author_headers)
    assert response.status_code == status.HTTP_201_CREATED
    return response.json()


async def _submit_survey_response(
    client, headers, survey, event_at, response_number: int | None = 1, **overrides
):
    """Submit to an anonymous survey, which carries no target entity."""
    question = survey["questions"][0]
    body = {
        "survey_id": survey["id"],
        "answers": {question["id"]: question["options"][0]["id"]},
        "response_number": response_number,
        "event_at": event_at,
        **overrides,
    }
    response = await client.post(
        _responses_url(survey["id"]), json=body, headers=headers
    )
    assert response.status_code == status.HTTP_201_CREATED
    return response.json()["id"]


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

    async def test_mixed_feed_includes_all_three_types_ordered_desc(
        self, client, db_establishment, field_worker_a, survey_author
    ):
        headers, _ = field_worker_a
        subject_id = await _create_subject(client, headers, dni=55555551)
        await _create_measurement(
            client, headers, subject_id, db_establishment.id, "2024-02-01T00:00:00Z"
        )
        survey = await _create_survey(client, survey_author)
        await _submit_survey_response(client, headers, survey, "2024-03-01T00:00:00Z")

        response = await client.get(ACTIVITY_URL, headers=headers)
        body = response.json()
        assert body["total"] == 3
        # subject's occurred_at is server-generated "now" (via subject_events),
        # so it sorts ahead of the client-dated 2024 measurement/response.
        assert [i["type"] for i in body["items"]] == [
            "subject",
            "survey_response",
            "measurement",
        ]


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


class TestFoodMovementTypeFilter:
    async def test_type_food_intake_returns_only_intakes(
        self, client, db_establishment, field_worker_a, foods
    ):
        headers, _ = field_worker_a
        subject_id = await _create_subject(client, headers, dni=66666661)
        await _create_measurement(
            client, headers, subject_id, db_establishment.id, "2024-02-01T00:00:00Z"
        )
        intake_id = await _create_food_intake(
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
                ACTIVITY_URL, params={"type": "food_intake"}, headers=headers
            )
        ).json()

        assert body["total"] == 1
        assert all(i["type"] == "food_intake" for i in body["items"])
        assert body["items"][0]["food_intake"]["id"] == intake_id

    async def test_type_food_outflow_returns_only_outflows(
        self, client, db_establishment, field_worker_a, foods
    ):
        headers, _ = field_worker_a
        subject_id = await _create_subject(client, headers, dni=66666662)
        await _create_measurement(
            client, headers, subject_id, db_establishment.id, "2024-02-01T00:00:00Z"
        )
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

        body = (
            await client.get(
                ACTIVITY_URL, params={"type": "food_outflow"}, headers=headers
            )
        ).json()

        assert body["total"] == 1
        assert all(i["type"] == "food_outflow" for i in body["items"])
        assert body["items"][0]["food_outflow"]["id"] == outflow_id

    async def test_unknown_type_is_rejected_with_422(self, client, field_worker_a):
        """Widening the enum must not turn `type` into a free-form string."""
        headers, _ = field_worker_a

        response = await client.get(
            ACTIVITY_URL, params={"type": "food_movement"}, headers=headers
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


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

    async def test_types_interleave_across_branches_by_occurred_at_desc(
        self, client, db_establishment, field_worker_a, foods
    ):
        """An intake dated between two outflows lands between them -- exactly
        what a client-side merge could not guarantee."""
        headers, _ = field_worker_a
        intake_a, outflow_1, intake_b, outflow_2 = await self._seed_two_direction_feed(
            client, headers, db_establishment.id, foods, dni=77777774
        )

        body = (
            await client.get(
                ACTIVITY_URL,
                params={"type": ["food_intake", "food_outflow"]},
                headers=headers,
            )
        ).json()

        returned = [_item_id(i) for i in body["items"]]
        assert (
            returned.index(outflow_1)
            < returned.index(intake_b)
            < returned.index(outflow_2)
        )
        assert returned[0] == intake_a

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

    async def test_omitted_type_returns_every_type(
        self, client, db_establishment, field_worker_a, foods
    ):
        headers, _ = field_worker_a
        await self._seed_two_direction_feed(
            client, headers, db_establishment.id, foods, dni=77777777
        )

        body = (await client.get(ACTIVITY_URL, headers=headers)).json()

        assert body["total"] == 6
        assert {i["type"] for i in body["items"]} == {
            "subject",
            "measurement",
            "food_intake",
            "food_outflow",
        }

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


class TestActivityItemTagging:
    async def test_food_rows_are_never_tagged_as_survey_response(
        self, client, db_establishment, field_worker_a, foods
    ):
        """Regression: `_assemble_items` used to end in a bare `else:` that
        treated every non-subject, non-measurement row as a survey response.
        A food row reaching that branch would be mis-tagged.

        Deliberately asserts on a feed with *no* survey responses in it, so the
        expected count of `survey_response` items is exactly zero.
        """
        headers, _ = field_worker_a
        intake_id = await _create_food_intake(
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

        assert [i["type"] for i in body["items"]] == ["food_outflow", "food_intake"]
        assert all(i["survey_response"] is None for i in body["items"])
        # Exactly one sibling populated per item, and its key name equals the
        # item's type — the general form of the flat-siblings contract, so it
        # catches a mis-tagging of any future type too.
        for item in body["items"]:
            assert _populated_siblings(item) == [item["type"]]
        assert body["items"][0]["food_outflow"]["id"] == outflow_id
        assert body["items"][1]["food_intake"]["id"] == intake_id

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
