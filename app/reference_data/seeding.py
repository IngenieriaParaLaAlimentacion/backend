"""Building blocks shared by the seeds that load fictitious datasets.

Each function takes the specs it loads, so the reference data and the load-test
data are seeded the same way. Running any of them again adds nothing that is
already there.
"""

from collections.abc import Iterable
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select

from app.config.settings import settings
from app.core.security import hash_password
from app.db.unit_of_work import UnitOfWork
from app.domain.survey import SurveyInstrumentType
from app.domain.user import UserActor, UserRole
from app.exceptions.domain_exceptions import EstablishmentAlreadyExistsError
from app.models.surveys.survey import Survey
from app.reference_data.fies_template import build_fies_template
from app.reference_data.reference_e2e_dataset import (
    ReferenceEstablishment,
    ReferenceUser,
)
from app.schemas.establishments.establishment_schema import EstablishmentRequest
from app.schemas.surveys.survey_schema import (
    OptionInput,
    QuestionInput,
    SurveyCreateRequest,
)
from app.services.establishments.establishment_service import EstablishmentService
from app.services.surveys.survey_service import SurveyService

# Named on purpose: an environment that was never set defaults to "development",
# so refusing only "production" would let a seed run wherever ENVIRONMENT is missing.
_ALLOWED_ENVIRONMENTS = {"development", "e2e"}


def position(item) -> int:
    """Return the position a survey question or option is shown at."""
    return item.position


def refuse_outside_test_environments(dataset_name: str) -> None:
    """Exit unless ENVIRONMENT names one of the environments a seed may run in."""
    if settings.environment.lower() not in _ALLOWED_ENVIRONMENTS:
        raise SystemExit(
            f"The {dataset_name} only loads when ENVIRONMENT is test or e2e, "
            f"not {settings.environment!r}."
        )


async def seed_users(
    uow: UnitOfWork, users: Iterable[ReferenceUser], password: str
) -> dict[str, UUID]:
    """Create the users that are missing and return their ids by key."""
    now = datetime.now(timezone.utc)
    user_ids: dict[str, UUID] = {}
    for spec in users:
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
                user_id=user.id, password_hashed=hash_password(password)
            )
        user_ids[spec.key] = user.id
    await uow.commit()
    return user_ids


async def seed_establishments(
    uow: UnitOfWork, establishments: Iterable[ReferenceEstablishment]
) -> dict[str, UUID]:
    """Create the establishments that are missing and return their ids by key."""
    service = EstablishmentService(uow)
    establishment_ids: dict[str, UUID] = {}
    for spec in establishments:
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


async def seed_access(
    uow: UnitOfWork,
    users: Iterable[ReferenceUser],
    user_ids: dict[str, UUID],
    establishment_ids: dict[str, UUID],
) -> None:
    """Give each user the approved or pending access it is meant to have."""
    for spec in users:
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


def field_workers_by_establishment(
    users: Iterable[ReferenceUser], user_ids: dict[str, UUID]
) -> dict[str, UserActor]:
    """Return, for each establishment, the field worker who works in it."""
    actors: dict[str, UserActor] = {}
    for spec in users:
        if spec.role != UserRole.FIELD_WORKER:
            continue
        actor = UserActor(user_id=user_ids[spec.key], role=spec.role)
        for key in spec.approved_establishments:
            actors.setdefault(key, actor)
    return actors


async def seed_fies_survey(uow: UnitOfWork, admin: UserActor, name: str) -> UUID:
    """Create the FIES survey named ``name`` if it is missing and return its id."""
    existing = await uow.session.execute(select(Survey.id).where(Survey.name == name))
    survey_id = existing.scalar_one_or_none()
    if survey_id is not None:
        return survey_id

    template = build_fies_template()
    survey = await SurveyService(uow).create(
        SurveyCreateRequest(
            name=name,
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
                        for option in sorted(question.options, key=position)
                    ],
                )
                for question in sorted(template.questions, key=position)
            ],
        ),
        admin,
    )
    return survey.id
