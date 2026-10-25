"""Load the fictitious reference dataset into a database.

Run it by hand against a disposable database, once the migrations and the other seeds
have run. It is not part of the service startup or the deploy, and it only runs when
ENVIRONMENT is test or e2e. Running it again adds nothing that is already there.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select

from app.config.logging import setup_logging
from app.config.settings import settings
from app.core.security import hash_password
from app.db.unit_of_work import UnitOfWork
from app.domain.establishment import EstablishmentRequestStatus
from app.domain.survey import SurveyDomain, SurveyInstrumentType
from app.domain.user import UserActor, UserRole
from app.exceptions.domain_exceptions import EstablishmentAlreadyExistsError
from app.models.establishments.establishment_request import (
    EstablishmentRequest as EstablishmentRequestModel,
)
from app.models.food_catalog.food import Food
from app.models.surveys.survey import Survey
from app.reference_data.fies_template import build_fies_template
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
from app.schemas.establishments.establishment_schema import EstablishmentRequest
from app.schemas.food_intakes.food_intake_schema import (
    FoodIntakeRequest,
    FoodLineRequest,
)
from app.schemas.food_outflows.food_outflow_schema import FoodOutflowRequest
from app.schemas.measurements.measurement_schema import MeasurementRequest
from app.schemas.subjects.subject_schema import SubjectRequest
from app.schemas.surveys.survey_response_schema import SurveyResponseRequest
from app.schemas.surveys.survey_schema import (
    OptionInput,
    QuestionInput,
    SurveyCreateRequest,
)
from app.services.establishments.establishment_service import EstablishmentService
from app.services.food_intakes.food_intake_service import FoodIntakeService
from app.services.food_outflows.food_outflow_service import FoodOutflowService
from app.services.measurements.measurement_service import MeasurementService
from app.services.subjects.subject_service import SubjectService
from app.services.surveys.survey_response_service import SurveyResponseService
from app.services.surveys.survey_service import SurveyService

setup_logging()
logger = logging.getLogger(__name__)

# Named on purpose: an environment that was never set defaults to "development",
# so refusing only "production" would let the seed run wherever ENVIRONMENT is missing.
_ALLOWED_ENVIRONMENTS = {"test", "e2e"}


def _refuse_outside_test_environments() -> None:
    """Exit unless ENVIRONMENT names one of the environments the seed may run in."""
    if settings.environment.lower() not in _ALLOWED_ENVIRONMENTS:
        raise SystemExit(
            "The reference data only loads when ENVIRONMENT is test or e2e, "
            f"not {settings.environment!r}."
        )


async def _seed_users(uow: UnitOfWork) -> dict[str, UUID]:
    """Create the users that are missing and return their ids by key."""
    now = datetime.now(timezone.utc)
    user_ids: dict[str, UUID] = {}
    for spec in USERS:
        user = await uow.user_repo.get_by_email(spec.email)
        if user is None:
            user = await uow.user_repo.create(
                email=spec.email,
                name=spec.name,
                last_name=spec.last_name,
                role=spec.role,
                status=spec.status,
                is_email_verified=True,
            )
            user.email_verified_at = now
            await uow.password_repo.create(
                user_id=user.id, password_hashed=hash_password(PASSWORD)
            )
        user_ids[spec.key] = user.id
    await uow.commit()
    return user_ids


async def _seed_establishments(uow: UnitOfWork) -> dict[str, UUID]:
    """Create the establishments that are missing and return their ids by key."""
    service = EstablishmentService(uow)
    establishment_ids: dict[str, UUID] = {}
    for spec in ESTABLISHMENTS:
        try:
            created = await service.create_establishment(
                EstablishmentRequest(
                    name=spec.name,
                    formatted_address=spec.formatted_address,
                    latitude=spec.latitude,
                    longitude=spec.longitude,
                    place_id=spec.place_id,
                    city=spec.city,
                    province=spec.province,
                )
            )
            establishment_ids[spec.key] = created.id
        except EstablishmentAlreadyExistsError:
            existing = await uow.establishment_repo.get_by_place_id(spec.place_id)
            establishment_ids[spec.key] = existing.id
    return establishment_ids


async def _seed_access(
    uow: UnitOfWork, user_ids: dict[str, UUID], establishment_ids: dict[str, UUID]
) -> None:
    """Give each user the approved or pending access it is meant to have."""
    for spec in USERS:
        user_id = user_ids[spec.key]
        approved = [establishment_ids[key] for key in spec.approved_establishments]
        if approved:
            await uow.user_establishment_repo.approve_relations(user_id, approved)
        for key in spec.pending_establishments:
            relation = await uow.user_establishment_repo.get_relation(
                user_id, establishment_ids[key]
            )
            if relation is None:
                await uow.user_establishment_repo.preset_relation(
                    user_id, establishment_ids[key]
                )
    await uow.commit()


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


def _field_workers_by_establishment(
    user_ids: dict[str, UUID],
) -> dict[str, UserActor]:
    """Return, for each establishment, the field worker who works in it."""
    actors: dict[str, UserActor] = {}
    for spec in USERS:
        if spec.role != UserRole.FIELD_WORKER:
            continue
        actor = UserActor(user_id=user_ids[spec.key], role=spec.role)
        for key in spec.approved_establishments:
            actors.setdefault(key, actor)
    return actors


async def _seed_subjects_and_measurements(
    uow: UnitOfWork,
    establishment_ids: dict[str, UUID],
    actors: dict[str, UserActor],
) -> None:
    """Register the subjects and their measurements; registered ones are kept."""
    subjects = SubjectService(uow)
    measurements = MeasurementService(uow)
    now = datetime.now(timezone.utc)
    for spec in SUBJECTS:
        actor = actors[spec.establishment]
        subject_id = reference_id("subject", spec.key)
        await subjects.create_subject(
            SubjectRequest(
                id=subject_id,
                dni=spec.dni,
                sex=spec.sex,
                name=spec.name,
                last_name=spec.last_name,
                birth_date=spec.birth_date(now.date()),
                is_rural=spec.is_rural,
                is_indigenous=spec.is_indigenous,
            ),
            actor.user_id,
        )
        for number, reading in enumerate(spec.readings):
            await measurements.register(
                MeasurementRequest(
                    id=reference_id("measurement", spec.key, str(number)),
                    subject_id=subject_id,
                    establishment_id=establishment_ids[spec.establishment],
                    weight_kg=reading.weight_kg,
                    height_cm=reading.height_cm,
                    measured_at=now - timedelta(days=reading.days_ago),
                ),
                actor,
            )


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


async def _seed_fies_survey(uow: UnitOfWork, admin: UserActor) -> UUID:
    """Create the FIES survey if it is missing and return its id."""
    existing = await uow.session.execute(
        select(Survey.id).where(Survey.name == FIES_SURVEY_NAME)
    )
    survey_id = existing.scalar_one_or_none()
    if survey_id is not None:
        return survey_id

    template = build_fies_template()
    survey = await SurveyService(uow).create(
        SurveyCreateRequest(
            name=FIES_SURVEY_NAME,
            description=template.description,
            response_target=template.response_target,
            instrument_type=SurveyInstrumentType.FIES,
            requires_response_number=template.requires_response_number,
            questions=[
                QuestionInput(
                    text=question.text,
                    response_type=question.response_type,
                    is_required=question.is_required,
                    options=[
                        OptionInput(text=option.text)
                        for option in sorted(question.options, key=_position)
                    ],
                )
                for question in sorted(template.questions, key=_position)
            ],
        ),
        admin,
    )
    return survey.id


def _position(item) -> int:
    return item.position


async def _seed_fies_responses(survey_id: UUID, actors: list[UserActor]) -> None:
    """Submit the FIES responses that are missing, spread over the field workers."""
    async with UnitOfWork() as uow:
        survey = SurveyDomain.from_db(await uow.survey_repo.get_by_id(survey_id))
    questions = sorted(survey.questions, key=_position)
    now = datetime.now(timezone.utc)
    for number, score in enumerate(FIES_SCORES, start=1):
        # "Sí" is the first option; the first `score` questions get it.
        answers = {}
        for index, question in enumerate(questions):
            options = sorted(question.options, key=_position)
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
    _refuse_outside_test_environments()
    async with UnitOfWork() as uow:
        user_ids = await _seed_users(uow)
        establishment_ids = await _seed_establishments(uow)
        await _seed_access(uow, user_ids, establishment_ids)
        await _seed_establishment_requests(uow, user_ids)

        actors = _field_workers_by_establishment(user_ids)
        await _seed_subjects_and_measurements(uow, establishment_ids, actors)
        await _seed_stock_movements(uow, establishment_ids, actors)

        admin = UserActor(user_id=user_ids["admin"], role=UserRole.ADMIN)
        survey_id = await _seed_fies_survey(uow, admin)
        await _seed_fies_responses(survey_id, list(actors.values()))
    logger.info("Reference data loaded")


if __name__ == "__main__":
    asyncio.run(seed_reference_e2e())
