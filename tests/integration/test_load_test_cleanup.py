"""The load-test cleanup, run against a real database."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.core.security import create_access_token
from app.domain.user import UserRole
from app.models.auth.user import User
from app.models.food_intakes.food_intake import FoodIntake
from app.models.food_stock.food_stock import FoodStock
from app.models.measurements.measurement import Measurement
from app.models.subjects.subject import Subject
from app.models.subjects.subject_event import SubjectEvent
from app.models.surveys.survey import Survey
from app.models.surveys.survey_response import SurveyResponse
from tests.integration.urls import MEASUREMENTS_URL, SUBJECTS_URL, SURVEYS_URL
from tests.load.data import cleanup, seed
from tests.load.data.dataset import (
    FIES_SURVEY_NAME,
    MARKER,
    SUBJECTS,
    load_test_id,
)

COUNTED_MODELS = (
    Subject,
    SubjectEvent,
    Measurement,
    FoodIntake,
    FoodStock,
    SurveyResponse,
)
FOOD_INTAKES_URL = "/api/v1/food-intakes"


@pytest.fixture(autouse=True)
async def seeded(app, monkeypatch):
    """Seed a few load-test subjects."""
    monkeypatch.setenv("LOAD_TEST_PASSWORD", "Carga-Test-123!")
    monkeypatch.setattr(seed, "SUBJECTS", SUBJECTS[:3])
    monkeypatch.setattr(cleanup, "SUBJECTS", SUBJECTS[:3])
    await seed.seed()


async def _row_counts() -> dict[str, int]:
    from app.db.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        return {
            model.__tablename__: await session.scalar(
                select(func.count()).select_from(model)
            )
            for model in COUNTED_MODELS
        }


async def _load_test_worker() -> tuple[dict, str]:
    """Return the headers and establishment id of the first load-test field worker."""
    from app.db.database import AsyncSessionLocal

    subject = SUBJECTS[0]
    async with AsyncSessionLocal() as session:
        user_id = await session.scalar(
            select(User.id).where(User.email == "loadtest.relevador01@tpp.com")
        )
        establishment_id = await session.scalar(
            select(Measurement.establishment_id).where(
                Measurement.subject_id == load_test_id("subject", subject.key)
            )
        )
    token = create_access_token(user_id, role=UserRole.FIELD_WORKER)
    return {"Authorization": f"Bearer {token}"}, str(establishment_id)


async def _write_like_a_load_test(client, foods) -> None:
    """Send one record of every kind the load tests write."""
    headers, establishment_id = await _load_test_worker()
    now = datetime.now(timezone.utc).isoformat()
    subject_id = str(uuid4())
    responses = [
        await client.post(
            SUBJECTS_URL,
            headers=headers,
            json={
                "id": subject_id,
                "dni": 81_000_001,
                "sex": "female",
                "name": "Nueva",
                "last_name": f"{MARKER} Gómez",
                "birth_date": "2020-01-01",
                "is_rural": False,
                "is_indigenous": False,
            },
        ),
        await client.post(
            MEASUREMENTS_URL,
            headers=headers,
            json={
                "id": str(uuid4()),
                "subject_id": subject_id,
                "establishment_id": establishment_id,
                "weight_kg": 15.0,
                "height_cm": 95.0,
                "measured_at": now,
            },
        ),
        await client.post(
            FOOD_INTAKES_URL,
            headers=headers,
            json={
                "id": str(uuid4()),
                "establishment_id": establishment_id,
                "occurred_at": now,
                "comments": MARKER,
                "origin_type": "national_government",
                "is_recurring": False,
                "items": [{"food_id": str(foods.rice), "quantity": "5"}],
            },
        ),
    ]
    available = await client.get(f"{SURVEYS_URL}/available", headers=headers)
    survey = next(
        item for item in available.json()["items"] if item["name"] == FIES_SURVEY_NAME
    )
    detail = (await client.get(f"{SURVEYS_URL}/{survey['id']}", headers=headers)).json()
    responses.append(
        await client.post(
            f"{SURVEYS_URL}/{survey['id']}/responses",
            headers=headers,
            json={
                "id": str(uuid4()),
                "answers": {
                    question["id"]: question["options"][0]["id"]
                    for question in detail["questions"]
                },
                "response_number": 1,
                "event_at": now,
            },
        )
    )
    assert [response.status_code for response in responses] == [201] * 4


async def test_removes_what_a_run_wrote_and_keeps_the_seed(client, foods):
    seeded = await _row_counts()
    await _write_like_a_load_test(client, foods)

    await cleanup.cleanup()

    assert await _row_counts() == seeded


async def test_resets_the_survey_response_count(client, foods):
    from app.db.database import AsyncSessionLocal

    await _write_like_a_load_test(client, foods)

    await cleanup.cleanup()

    async with AsyncSessionLocal() as session:
        count = await session.scalar(
            select(Survey.response_count).where(Survey.name == FIES_SURVEY_NAME)
        )
    assert count == 0


async def test_keeps_records_outside_the_load_test_data(
    client, db_establishment, field_worker_with_access
):
    headers, _ = field_worker_with_access
    subject_id = str(uuid4())
    subject = await client.post(
        SUBJECTS_URL,
        headers=headers,
        json={
            "id": subject_id,
            "dni": 30_111_222,
            "sex": "female",
            "name": "María",
            # Carries the marker, but was not written by a load-test user.
            "last_name": f"{MARKER} Gómez",
            "birth_date": "2018-05-02",
            "is_rural": False,
            "is_indigenous": False,
        },
    )
    measurement = await client.post(
        MEASUREMENTS_URL,
        headers=headers,
        json={
            "id": str(uuid4()),
            "subject_id": subject_id,
            "establishment_id": str(db_establishment.id),
            "weight_kg": 20.0,
            "height_cm": 110.0,
            "measured_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    assert (subject.status_code, measurement.status_code) == (201, 201)
    before = await _row_counts()

    await cleanup.cleanup()

    assert await _row_counts() == before
