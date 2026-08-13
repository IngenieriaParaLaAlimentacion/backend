import uuid

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


async def _create_survey(client, author_headers, name: str = "Encuesta A"):
    body = {
        "name": name,
        "description": None,
        "scope": "generic",
        "questions": [
            {
                "text": "¿Comió hoy?",
                "response_type": "single_choice",
                "is_required": True,
                "options": [{"text": "Sí"}, {"text": "No"}],
            }
        ],
        "establishment_ids": [],
    }
    response = await client.post(SURVEYS_URL, json=body, headers=author_headers)
    assert response.status_code == status.HTTP_201_CREATED
    return response.json()


async def _submit_survey_response(
    client, headers, survey, establishment_id, event_at, **overrides
):
    question = survey["questions"][0]
    body = {
        "survey_id": survey["id"],
        "establishment_id": str(establishment_id),
        "answers": {question["id"]: question["options"][0]["id"]},
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
            client, headers, survey, db_establishment.id, "2024-01-01T00:00:00Z"
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
    async def test_submitted_response_appears_for_submitter(
        self, client, db_establishment, field_worker_a, survey_author
    ):
        headers, _ = field_worker_a
        survey = await _create_survey(client, survey_author)
        response_id = await _submit_survey_response(
            client, headers, survey, db_establishment.id, "2024-01-01T00:00:00Z"
        )

        response = await client.get(ACTIVITY_URL, headers=headers)
        body = response.json()
        assert body["total"] == 1
        item = body["items"][0]
        assert item["type"] == "survey_response"
        assert item["survey_response"]["id"] == response_id
        assert item["survey_response"]["establishment"]["id"] == str(
            db_establishment.id
        )

    async def test_does_not_leak_to_other_submitters(
        self, client, db_establishment, field_worker_a, field_worker_b, survey_author
    ):
        headers_a, _ = field_worker_a
        headers_b, _ = field_worker_b
        survey = await _create_survey(client, survey_author)
        await _submit_survey_response(
            client, headers_a, survey, db_establishment.id, "2024-01-01T00:00:00Z"
        )

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
        await _submit_survey_response(
            client, headers, survey, db_establishment.id, "2024-03-01T00:00:00Z"
        )

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
