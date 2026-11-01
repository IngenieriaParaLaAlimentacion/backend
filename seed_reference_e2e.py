"""Load the fictitious reference dataset into a database.

Run it by hand against a disposable database, once the migrations and the other seeds
have run. It is not part of the service startup or the deploy, and it only runs when
ENVIRONMENT is e2e. Running it again is idempotent.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select

from app.config.logging import setup_logging
from app.db.unit_of_work import UnitOfWork
from app.domain.establishment import EstablishmentRequestStatus
from app.domain.survey import SurveyDomain
from app.domain.user import UserActor, UserRole
from app.models.establishments.establishment_request import (
    EstablishmentRequest as EstablishmentRequestModel,
)
from app.models.food_catalog.food import Food
from app.reference_data.reference_e2e_dataset import (
    ESTABLISHMENT_REQUESTS,
    ESTABLISHMENTS,
    FIES_SCORES,
    FIES_SURVEY_NAME,
    INTAKES,
    OUTFLOWS,
    PASSWORD,
    SUBJECTS,
    USERS,
    reference_id,
)
from app.reference_data.seeding import (
    field_workers_by_establishment,
    position,
    refuse_outside_environment,
    seed_access,
    seed_establishments,
    seed_fies_survey,
    seed_subjects_and_measurements,
    seed_users,
)
from app.schemas.food_intakes.food_intake_schema import (
    FoodIntakeRequest,
    FoodLineRequest,
)
from app.schemas.food_outflows.food_outflow_schema import FoodOutflowRequest
from app.schemas.surveys.survey_response_schema import SurveyResponseRequest
from app.services.food_intakes.food_intake_service import FoodIntakeService
from app.services.food_outflows.food_outflow_service import FoodOutflowService
from app.services.surveys.survey_response_service import SurveyResponseService

setup_logging()
logger = logging.getLogger(__name__)


async def _seed_establishment_requests(
    uow: UnitOfWork, user_ids: dict[str, UUID]
) -> None:
    """Create the pending establishment requests that are missing."""
    for spec in ESTABLISHMENT_REQUESTS:
        request_id = reference_id("establishment-request", spec.key)
        if await uow.establishment_request_repo.get_by_id(request_id) is not None:
            continue
        await uow.establishment_request_repo.create(
            EstablishmentRequestModel(
                id=request_id,
                user_id=user_ids[spec.requested_by],
                status=EstablishmentRequestStatus.PENDING,
                name=spec.name,
                formatted_address=spec.formatted_address,
                city=spec.city,
                province=spec.province,
            )
        )
    await uow.commit()


async def _food_ids_by_code(uow: UnitOfWork) -> dict[str, UUID]:
    """Return the id of every catalog food the dataset moves, by code."""
    codes = {code for template in (*INTAKES, *OUTFLOWS) for code, _ in template.items}
    result = await uow.session.execute(select(Food).where(Food.code.in_(codes)))
    food_ids = {food.code: food.id for food in result.scalars()}
    missing = codes - set(food_ids)
    if missing:
        raise SystemExit(f"Foods missing from the catalog: {sorted(missing)}")
    return food_ids


def _lines(
    items: tuple[tuple[str, int], ...], food_ids: dict[str, UUID], scale: float
) -> list[FoodLineRequest]:
    """Build the request lines, with quantities rounded to whole units."""
    return [
        FoodLineRequest(
            food_id=food_ids[code], quantity=Decimal(max(1, round(quantity * scale)))
        )
        for code, quantity in items
    ]


async def _seed_stock_movements(
    uow: UnitOfWork,
    establishment_ids: dict[str, UUID],
    actors: dict[str, UserActor],
) -> None:
    """Register the deliveries and outflows; registered ones leave stock as is."""
    food_ids = await _food_ids_by_code(uow)
    intakes = FoodIntakeService(uow)
    outflows = FoodOutflowService(uow)
    now = datetime.now(timezone.utc)
    for spec in ESTABLISHMENTS:
        actor = actors[spec.key]
        # All deliveries go in first, so no outflow asks for more than is held.
        for template in INTAKES:
            await intakes.register(
                FoodIntakeRequest(
                    id=reference_id("intake", spec.key, template.key),
                    establishment_id=establishment_ids[spec.key],
                    occurred_at=now - timedelta(days=template.days_ago),
                    comments=template.comments,
                    origin_type=template.origin_type,
                    is_recurring=template.is_recurring,
                    items=_lines(template.items, food_ids, spec.stock_scale),
                ),
                actor,
            )
        for template in OUTFLOWS:
            await outflows.register(
                FoodOutflowRequest(
                    id=reference_id("outflow", spec.key, template.key),
                    establishment_id=establishment_ids[spec.key],
                    occurred_at=now - timedelta(days=template.days_ago),
                    comments=template.comments,
                    category=template.category,
                    items=_lines(template.items, food_ids, spec.stock_scale),
                ),
                actor,
            )


async def _seed_fies_responses(survey_id: UUID, actors: list[UserActor]) -> None:
    """Submit the FIES responses that are missing, spread over the field workers."""
    async with UnitOfWork() as uow:
        survey = SurveyDomain.from_db(await uow.survey_repo.get_by_id(survey_id))
    questions = sorted(survey.questions, key=position)
    now = datetime.now(timezone.utc)
    for number, score in enumerate(FIES_SCORES, start=1):
        # "Sí" is the first option; the first `score` questions get it.
        answers = {}
        for index, question in enumerate(questions):
            options = sorted(question.options, key=position)
            answers[str(question.id)] = str(options[0 if index < score else 1].id)
        # A response updates the survey's counter, so a session shared by several
        # responses would read the survey stale. Each one gets its own, as a request.
        async with UnitOfWork() as response_uow:
            await SurveyResponseService(response_uow).submit(
                survey_id,
                SurveyResponseRequest(
                    id=reference_id("fies-response", str(number)),
                    answers=answers,
                    response_number=number,
                    event_at=now - timedelta(days=2 * number),
                ),
                actors[number % len(actors)],
            )


async def seed_reference_e2e() -> None:
    """Load the whole reference dataset."""
    refuse_outside_environment("e2e", "reference data")
    async with UnitOfWork() as uow:
        user_ids = await seed_users(uow, USERS, PASSWORD)
        establishment_ids = await seed_establishments(uow, ESTABLISHMENTS)
        await seed_access(uow, USERS, user_ids, establishment_ids)
        await _seed_establishment_requests(uow, user_ids)

        actors = field_workers_by_establishment(USERS, user_ids)
        await seed_subjects_and_measurements(
            uow, SUBJECTS, establishment_ids, actors, reference_id
        )
        await _seed_stock_movements(uow, establishment_ids, actors)

        admin = UserActor(user_id=user_ids["admin"], role=UserRole.ADMIN)
        survey_id = await seed_fies_survey(uow, admin, FIES_SURVEY_NAME)
        # Response n is submitted by the field worker of the n-th establishment. A
        # replay has to come from the same user, so this assignment must not change.
        submitters = [actors[spec.key] for spec in ESTABLISHMENTS]
        await _seed_fies_responses(survey_id, submitters)
    logger.info("Reference data loaded")


if __name__ == "__main__":
    asyncio.run(seed_reference_e2e())
