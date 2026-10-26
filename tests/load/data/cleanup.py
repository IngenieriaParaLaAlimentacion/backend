"""Remove what the load tests wrote, keeping the seeded load-test dataset.

``tests/load/run.sh`` runs it before the load tests, in case an earlier run stopped
halfway, and again after them, so every run starts from the same data. It only
touches rows that belong to the load-test establishments and users, all in one
transaction, against the database in ``DATABASE_URL``.

    poetry run python -m tests.load.data.cleanup
"""

import asyncio
import logging
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.logging import setup_logging
from app.models.auth.user import User
from app.models.auth.user_token import UserToken
from app.models.establishments.establishment import Establishment
from app.models.food_intakes.food_intake import FoodIntake
from app.models.food_outflows.food_outflow import FoodOutflow
from app.models.food_stock.food_stock import FoodStock
from app.models.measurements.measurement import Measurement
from app.models.subjects.subject import Subject
from app.models.subjects.subject_event import SubjectEvent
from app.models.surveys.survey import Survey
from app.models.surveys.survey_response import SurveyResponse
from tests.load.data.dataset import (
    ESTABLISHMENTS,
    FIES_SURVEY_NAME,
    MARKER,
    SUBJECTS,
    USERS,
    load_test_id,
)

setup_logging()
logger = logging.getLogger(__name__)


def _seeded_subject_ids() -> list[UUID]:
    return [load_test_id("subject", spec.key) for spec in SUBJECTS]


def _seeded_measurement_ids() -> list[UUID]:
    return [
        load_test_id("measurement", spec.key, str(number))
        for spec in SUBJECTS
        for number in range(len(spec.readings))
    ]


async def _ids(session: AsyncSession, statement) -> list[UUID]:
    return list((await session.scalars(statement)).all())


async def _delete(session: AsyncSession, statement) -> int:
    return (await session.execute(statement)).rowcount


async def _clean(session: AsyncSession) -> dict[str, int]:
    # Matched on the dataset's exact values, never on a pattern, so a row only goes
    # when it hangs off a load-test establishment or user.
    establishment_ids = await _ids(
        session,
        select(Establishment.id).where(
            Establishment.place_id.in_([spec.place_id for spec in ESTABLISHMENTS])
        ),
    )
    user_ids = await _ids(
        session, select(User.id).where(User.email.in_([u.email for u in USERS]))
    )
    survey_ids = await _ids(
        session, select(Survey.id).where(Survey.name == FIES_SURVEY_NAME)
    )
    # Subjects have no establishment; the ones a run created are known by their
    # creator, their marker and not being part of the seed.
    run_subject_ids = await _ids(
        session,
        select(Subject.id)
        .where(
            Subject.id.in_(
                select(SubjectEvent.subject_id).where(
                    SubjectEvent.actor_id.in_(user_ids)
                )
            ),
            Subject.last_name.startswith(MARKER),
            Subject.id.not_in(_seeded_subject_ids()),
        )
        .distinct(),
    )

    removed = {}
    # The seed submits no responses and moves no stock, so all of these are the run's.
    removed["survey_responses"] = await _delete(
        session,
        delete(SurveyResponse).where(
            SurveyResponse.survey_id.in_(survey_ids),
            SurveyResponse.submitted_by_id.in_(user_ids),
        ),
    )
    await session.execute(
        update(Survey)
        .where(Survey.id.in_(survey_ids))
        .values(
            response_count=select(func.count())
            .where(SurveyResponse.survey_id == Survey.id)
            .scalar_subquery()
        )
    )
    removed["food_intakes"] = await _delete(
        session,
        delete(FoodIntake).where(
            FoodIntake.establishment_id.in_(establishment_ids),
            FoodIntake.responsible_id.in_(user_ids),
        ),
    )
    removed["food_outflows"] = await _delete(
        session,
        delete(FoodOutflow).where(
            FoodOutflow.establishment_id.in_(establishment_ids),
            FoodOutflow.responsible_id.in_(user_ids),
        ),
    )
    removed["food_stock"] = await _delete(
        session,
        delete(FoodStock).where(FoodStock.establishment_id.in_(establishment_ids)),
    )
    removed["measurements"] = await _delete(
        session,
        delete(Measurement).where(
            Measurement.establishment_id.in_(establishment_ids),
            Measurement.responsible_id.in_(user_ids),
            Measurement.id.not_in(_seeded_measurement_ids()),
        ),
    )
    removed["subject_events"] = await _delete(
        session,
        delete(SubjectEvent).where(SubjectEvent.subject_id.in_(run_subject_ids)),
    )
    removed["subjects"] = await _delete(
        session, delete(Subject).where(Subject.id.in_(run_subject_ids))
    )
    # Every login leaves a refresh token behind.
    removed["user_tokens"] = await _delete(
        session, delete(UserToken).where(UserToken.user_id.in_(user_ids))
    )
    return removed


async def cleanup() -> dict[str, int]:
    """Remove every row a load test wrote and return how many went, by table."""
    from app.db.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session, session.begin():
        removed = await _clean(session)
    logger.info("Load-test writes removed", extra=removed)
    return removed


if __name__ == "__main__":
    asyncio.run(cleanup())
