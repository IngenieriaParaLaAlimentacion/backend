"""The load-test data seed, run against a real database."""

from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.models.auth.user import User
from app.models.establishments.establishment import Establishment
from app.models.measurements.measurement import Measurement
from app.models.subjects.subject import Subject
from app.models.surveys.survey import Survey
from tests.integration.urls import LOGIN_URL
from tests.load.data import seed
from tests.load.data.dataset import SUBJECTS, USERS

SEEDED_MODELS = (User, Establishment, Subject, Measurement, Survey)
PASSWORD = "Carga-Test-123!"


@pytest.fixture(autouse=True)
def small_dataset(monkeypatch):
    """Seed a few subjects instead of the full volume."""
    monkeypatch.setenv("LOAD_TEST_PASSWORD", PASSWORD)
    monkeypatch.setattr(seed, "SUBJECTS", SUBJECTS[:3])


async def _row_counts() -> dict[str, int]:
    from app.db.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        return {
            model.__tablename__: await session.scalar(
                select(func.count()).select_from(model)
            )
            for model in SEEDED_MODELS
        }


async def test_loads_every_kind_of_record_and_a_rerun_adds_nothing(app):
    await seed.seed()
    first = await _row_counts()
    await seed.seed()

    assert all(count > 0 for count in first.values())
    assert await _row_counts() == first


async def test_every_user_logs_in_with_the_load_test_password(client):
    await seed.seed()

    statuses = set()
    for spec in USERS:
        response = await client.post(
            LOGIN_URL,
            json={"email": spec.email, "password": PASSWORD, "device_id": str(uuid4())},
        )
        statuses.add(response.status_code)

    assert statuses == {200}


async def test_refuses_to_run_without_a_password(app, monkeypatch):
    monkeypatch.delenv("LOAD_TEST_PASSWORD")

    with pytest.raises(SystemExit):
        await seed.seed()

    assert (await _row_counts())["users"] == 0
