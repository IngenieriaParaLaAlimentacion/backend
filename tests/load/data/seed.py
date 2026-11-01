"""Load the fictitious dataset the load tests run against.

``tests/load/run.sh`` runs it before every load test, against the database in
``DATABASE_URL``, which is the only thing that picks the target. It needs
``LOAD_TEST_PASSWORD``. Once the whole dataset is in, a run only checks that and exits.

    poetry run python -m tests.load.data.seed
"""

import asyncio
import logging
import os

from app.config.logging import setup_logging
from app.db.unit_of_work import UnitOfWork
from app.domain.user import UserActor, UserRole
from app.reference_data.seeding import (
    field_workers_by_establishment,
    seed_access,
    seed_establishments,
    seed_fies_survey,
    seed_subjects_and_measurements,
    seed_users,
)
from tests.load.data.dataset import (
    ESTABLISHMENTS,
    FIES_SURVEY_NAME,
    SUBJECTS,
    USERS,
    load_test_id,
)

setup_logging()
logger = logging.getLogger(__name__)


async def _is_loaded(uow: UnitOfWork) -> bool:
    # Subjects go in last and in order, so the last one only exists after a full run.
    # A run that stopped halfway finds it missing and picks up where it left off.
    last_subject_id = load_test_id("subject", SUBJECTS[-1].key)
    return await uow.subject_repo.get_by_id(last_subject_id) is not None


async def seed() -> None:
    """Load the whole load-test dataset, unless it is already in."""
    password = os.environ.get("LOAD_TEST_PASSWORD")
    if not password:
        raise SystemExit("LOAD_TEST_PASSWORD must be set to load the load-test data.")

    async with UnitOfWork() as uow:
        if await _is_loaded(uow):
            logger.info("Load-test data already loaded; skipping seed")
            return

        user_ids = await seed_users(uow, USERS, password)
        establishment_ids = await seed_establishments(uow, ESTABLISHMENTS)
        await seed_access(uow, USERS, user_ids, establishment_ids)

        admin = UserActor(user_id=user_ids["admin"], role=UserRole.ADMIN)
        await seed_fies_survey(uow, admin, FIES_SURVEY_NAME)

        actors = field_workers_by_establishment(USERS, user_ids)
        await seed_subjects_and_measurements(
            uow, SUBJECTS, establishment_ids, actors, load_test_id
        )
    logger.info("Load-test data loaded", extra={"subjects": len(SUBJECTS)})


if __name__ == "__main__":
    asyncio.run(seed())
