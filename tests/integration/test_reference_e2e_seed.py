"""The reference data seed, run against a real database."""

from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.config.settings import settings
from app.domain.user import UserStatus
from app.models.auth.user import User
from app.models.establishments.establishment import Establishment
from app.models.establishments.establishment_request import EstablishmentRequest
from app.models.food_intakes.food_intake import FoodIntake
from app.models.food_outflows.food_outflow import FoodOutflow
from app.models.food_stock.food_stock import FoodStock
from app.models.measurements.measurement import Measurement
from app.models.subjects.subject import Subject
from app.models.surveys.survey import Survey
from app.models.surveys.survey_response import SurveyResponse
from app.reference_data.reference_e2e_dataset import PASSWORD, USERS
from tests.integration.urls import LOGIN_URL

SEEDED_MODELS = (
    User,
    Establishment,
    EstablishmentRequest,
    Subject,
    Measurement,
    FoodIntake,
    FoodOutflow,
    FoodStock,
    Survey,
    SurveyResponse,
)


@pytest.fixture(autouse=True)
def test_environment(monkeypatch):
    """Run the seed in an environment it is allowed in."""
    monkeypatch.setattr(settings, "environment", "test")


@pytest.fixture
async def catalog(app):
    """Load the food catalog, which the reference data moves stock of."""
    import seed_food_catalog

    await seed_food_catalog.seed_food_catalog()


async def _row_counts() -> dict[str, int]:
    from app.db.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        return {
            model.__tablename__: await session.scalar(
                select(func.count()).select_from(model)
            )
            for model in SEEDED_MODELS
        }


@pytest.mark.parametrize("environment", ["test", "e2e"])
async def test_loads_every_kind_of_record_and_a_rerun_adds_nothing(
    catalog, monkeypatch, environment
):
    import seed_reference_e2e

    monkeypatch.setattr(settings, "environment", environment)

    await seed_reference_e2e.seed_reference_e2e()
    first = await _row_counts()
    await seed_reference_e2e.seed_reference_e2e()

    assert all(count > 0 for count in first.values())
    assert await _row_counts() == first


async def test_users_log_in_according_to_their_status(catalog, client):
    import seed_reference_e2e

    await seed_reference_e2e.seed_reference_e2e()

    statuses = {}
    for spec in USERS:
        response = await client.post(
            LOGIN_URL,
            json={
                "email": spec.email,
                "password": PASSWORD,
                "device_id": str(uuid4()),
            },
        )
        statuses[spec.key] = response.status_code

    assert statuses == {
        spec.key: 200 if spec.status == UserStatus.ACTIVE else 403 for spec in USERS
    }


@pytest.mark.parametrize("environment", ["development", "production"])
async def test_refuses_to_run_outside_test_environments(app, monkeypatch, environment):
    import seed_reference_e2e

    monkeypatch.setattr(settings, "environment", environment)

    with pytest.raises(SystemExit):
        await seed_reference_e2e.seed_reference_e2e()

    assert (await _row_counts())["establishments"] == 0
