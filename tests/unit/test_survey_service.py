import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.pagination import PaginatedResult
from app.domain.survey import (
    QuestionInputData,
    ResponseType,
    SurveyDomain,
    SurveyListingParams,
    SurveyScope,
)
from app.domain.user import UserActor, UserRole
from app.exceptions.domain_exceptions import (
    EstablishmentNotFoundError,
    ForbiddenError,
    InvalidSurveyStructureError,
    SurveyAlreadyExistsError,
    SurveyLockedError,
    SurveyNotFoundError,
    UniqueConstraintError,
)
from app.schemas.survey_schema import (
    OptionInput,
    QuestionInput,
    SurveyCreateRequest,
    SurveyUpdateRequest,
)
from app.services.survey_service import SurveyService

# -- Builders --


def _text_question(text: str = "¿Cuál es su comida favorita?") -> QuestionInput:
    return QuestionInput(
        text=text, response_type=ResponseType.TEXT, is_required=False, options=[]
    )


def _choice_question(
    n_options: int = 2, texts: list[str] | None = None
) -> QuestionInput:
    if texts is None:
        texts = [f"Opción {i}" for i in range(n_options)]
    return QuestionInput(
        text="¿Con qué frecuencia?",
        response_type=ResponseType.SINGLE_CHOICE,
        is_required=True,
        options=[OptionInput(text=t) for t in texts],
    )


def _existing_question(
    is_required: bool = False,
    response_type: ResponseType = ResponseType.TEXT,
    option_ids: list[uuid.UUID] | None = None,
) -> MagicMock:
    """A MagicMock standing in for a persisted SurveyQuestion (with options)."""
    q = MagicMock()
    q.id = uuid.uuid4()
    q.response_type = response_type
    q.is_required = is_required
    q.options = []
    for option_id in option_ids or []:
        option = MagicMock()
        option.id = option_id
        q.options.append(option)
    return q


def make_create(**overrides) -> SurveyCreateRequest:
    data = dict(
        name="Encuesta A",
        description=None,
        scope=SurveyScope.GENERIC,
        questions=[_text_question()],
        establishment_ids=[],
    )
    data.update(overrides)
    return SurveyCreateRequest(**data)


def make_update(**overrides) -> SurveyUpdateRequest:
    data = dict(
        name="Encuesta A",
        description=None,
        scope=SurveyScope.GENERIC,
        questions=[_text_question()],
        establishment_ids=[],
    )
    data.update(overrides)
    return SurveyUpdateRequest(**data)


# -- Fixtures --


@pytest.fixture
def make_survey():
    def _make(
        created_by_id=None,
        response_count: int = 0,
        is_active: bool = True,
        name: str = "Encuesta A",
        scope: SurveyScope = SurveyScope.GENERIC,
        questions: list | None = None,
        establishments: list | None = None,
    ):
        s = MagicMock()
        s.id = uuid.uuid4()
        s.name = name
        s.description = None
        s.scope = scope
        s.created_by_id = created_by_id or uuid.uuid4()
        s.is_active = is_active
        s.response_count = response_count
        s.questions = questions if questions is not None else []
        s.establishments = establishments if establishments is not None else []
        s.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        s.updated_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        return s

    return _make


@pytest.fixture
def make_uow(make_survey):
    def _make(survey=None, name_exists=False, created=None, option_referenced=False):
        uow = AsyncMock()
        uow.survey_repo.name_exists = AsyncMock(return_value=name_exists)
        uow.survey_repo.get_by_id = AsyncMock(return_value=survey)
        uow.survey_repo.create = AsyncMock(return_value=created or make_survey())
        uow.survey_repo.reconcile = AsyncMock(return_value=survey or make_survey())
        uow.survey_repo.duplicate = AsyncMock(return_value=make_survey())
        uow.survey_repo.delete = AsyncMock()
        uow.survey_repo.update_active = AsyncMock(return_value=survey or make_survey())
        uow.establishment_repo.get_all_by_ids = AsyncMock(return_value=[])
        uow.user_establishment_repo.get_approved_establishment_ids = AsyncMock(
            return_value=set()
        )

        async def _get_referenced_option_ids(survey_id, pairs):
            return {option_id for _, option_id in pairs} if option_referenced else set()

        uow.survey_response_repo.get_referenced_option_ids = AsyncMock(
            side_effect=_get_referenced_option_ids
        )
        uow.commit = AsyncMock()
        return uow

    return _make


@pytest.fixture
def admin_actor():
    return UserActor(user_id=uuid.uuid4(), role=UserRole.ADMIN)


@pytest.fixture
def analyst_actor():
    return UserActor(user_id=uuid.uuid4(), role=UserRole.ANALYST)


@pytest.fixture
def field_worker_actor():
    return UserActor(user_id=uuid.uuid4(), role=UserRole.FIELD_WORKER)


class TestCreatePermissionsAndName:
    pytestmark = pytest.mark.asyncio

    async def test_field_worker_forbidden(self, make_uow, field_worker_actor):
        uow = make_uow()
        with pytest.raises(ForbiddenError):
            await SurveyService(uow).create(make_create(), field_worker_actor)
        uow.commit.assert_not_called()

    async def test_name_conflict_raises(self, make_uow, admin_actor):
        uow = make_uow(name_exists=True)
        with pytest.raises(SurveyAlreadyExistsError):
            await SurveyService(uow).create(make_create(), admin_actor)
        uow.survey_repo.create.assert_not_called()
        uow.commit.assert_not_called()

    async def test_unique_constraint_race_maps_to_conflict(self, make_uow, admin_actor):
        uow = make_uow()
        uow.survey_repo.create = AsyncMock(
            side_effect=UniqueConstraintError("name", "Encuesta A")
        )
        with pytest.raises(SurveyAlreadyExistsError):
            await SurveyService(uow).create(make_create(), admin_actor)
        uow.commit.assert_not_called()

    async def test_success_commits_and_returns_domain(self, make_uow, admin_actor):
        uow = make_uow()
        result = await SurveyService(uow).create(make_create(), admin_actor)
        assert isinstance(result, SurveyDomain)
        uow.commit.assert_called_once()

    async def test_create_passes_actor_as_author(self, make_uow, admin_actor):
        uow = make_uow()
        await SurveyService(uow).create(make_create(), admin_actor)
        _, kwargs = uow.survey_repo.create.call_args
        assert kwargs["created_by_id"] == admin_actor.user_id
        assert isinstance(kwargs["questions"][0], QuestionInputData)


class TestCreateStructureValidation:
    pytestmark = pytest.mark.asyncio

    async def test_zero_questions_rejected(self, make_uow, admin_actor):
        uow = make_uow()
        with pytest.raises(InvalidSurveyStructureError):
            await SurveyService(uow).create(make_create(questions=[]), admin_actor)

    async def test_over_thirty_questions_rejected(self, make_uow, admin_actor):
        uow = make_uow()
        data = make_create(questions=[_text_question() for _ in range(31)])
        with pytest.raises(InvalidSurveyStructureError):
            await SurveyService(uow).create(data, admin_actor)

    async def test_choice_below_min_options_rejected(self, make_uow, admin_actor):
        uow = make_uow()
        data = make_create(questions=[_choice_question(n_options=1)])
        with pytest.raises(InvalidSurveyStructureError):
            await SurveyService(uow).create(data, admin_actor)

    async def test_choice_above_max_options_rejected(self, make_uow, admin_actor):
        uow = make_uow()
        data = make_create(questions=[_choice_question(n_options=21)])
        with pytest.raises(InvalidSurveyStructureError):
            await SurveyService(uow).create(data, admin_actor)

    async def test_non_choice_with_options_rejected(self, make_uow, admin_actor):
        uow = make_uow()
        bad = QuestionInput(
            text="¿Edad?",
            response_type=ResponseType.NUMERIC,
            is_required=True,
            options=[OptionInput(text="18")],
        )
        with pytest.raises(InvalidSurveyStructureError):
            await SurveyService(uow).create(make_create(questions=[bad]), admin_actor)

    async def test_duplicate_options_rejected_case_insensitive(
        self, make_uow, admin_actor
    ):
        uow = make_uow()
        data = make_create(questions=[_choice_question(texts=["Sí", "sí "])])
        with pytest.raises(InvalidSurveyStructureError):
            await SurveyService(uow).create(data, admin_actor)

    async def test_targeted_requires_establishment(self, make_uow, admin_actor):
        uow = make_uow()
        data = make_create(scope=SurveyScope.TARGETED, establishment_ids=[])
        with pytest.raises(InvalidSurveyStructureError):
            await SurveyService(uow).create(data, admin_actor)

    async def test_generic_rejects_establishments(self, make_uow, admin_actor):
        uow = make_uow()
        data = make_create(scope=SurveyScope.GENERIC, establishment_ids=[uuid.uuid4()])
        with pytest.raises(InvalidSurveyStructureError):
            await SurveyService(uow).create(data, admin_actor)

    async def test_targeted_unknown_establishment_raises(self, make_uow, admin_actor):
        uow = make_uow()
        uow.establishment_repo.get_all_by_ids = AsyncMock(
            side_effect=EstablishmentNotFoundError(str(uuid.uuid4()))
        )
        data = make_create(scope=SurveyScope.TARGETED, establishment_ids=[uuid.uuid4()])
        with pytest.raises(EstablishmentNotFoundError):
            await SurveyService(uow).create(data, admin_actor)
        uow.commit.assert_not_called()

    async def test_targeted_with_valid_establishment_succeeds(
        self, make_uow, admin_actor
    ):
        uow = make_uow()
        est_id = uuid.uuid4()
        data = make_create(scope=SurveyScope.TARGETED, establishment_ids=[est_id])
        await SurveyService(uow).create(data, admin_actor)
        uow.establishment_repo.get_all_by_ids.assert_awaited_once_with([est_id])
        uow.commit.assert_called_once()


class TestGet:
    pytestmark = pytest.mark.asyncio

    async def test_missing_raises(self, make_uow, admin_actor):
        uow = make_uow(survey=None)
        with pytest.raises(SurveyNotFoundError):
            await SurveyService(uow).get(uuid.uuid4(), admin_actor)

    async def test_returns_domain(self, make_uow, make_survey, admin_actor):
        survey = make_survey()
        uow = make_uow(survey=survey)
        result = await SurveyService(uow).get(survey.id, admin_actor)
        assert isinstance(result, SurveyDomain)
        assert result.id == survey.id

    async def test_analyst_unrestricted_on_targeted_survey(
        self, make_uow, make_survey, analyst_actor
    ):
        """Analysts (an author role) are not scoped by establishment access."""
        survey = make_survey(
            scope=SurveyScope.TARGETED, establishments=[MagicMock(id=uuid.uuid4())]
        )
        uow = make_uow(survey=survey)
        result = await SurveyService(uow).get(survey.id, analyst_actor)
        assert result.id == survey.id
        uow.user_establishment_repo.get_approved_establishment_ids.assert_not_called()

    async def test_field_worker_generic_survey_succeeds(
        self, make_uow, make_survey, field_worker_actor
    ):
        survey = make_survey(scope=SurveyScope.GENERIC)
        uow = make_uow(survey=survey)
        result = await SurveyService(uow).get(survey.id, field_worker_actor)
        assert result.id == survey.id
        uow.user_establishment_repo.get_approved_establishment_ids.assert_not_called()

    async def test_field_worker_targeted_survey_with_access_succeeds(
        self, make_uow, make_survey, field_worker_actor
    ):
        establishment_id = uuid.uuid4()
        survey = make_survey(
            scope=SurveyScope.TARGETED,
            establishments=[MagicMock(id=establishment_id)],
        )
        uow = make_uow(survey=survey)
        uow.user_establishment_repo.get_approved_establishment_ids = AsyncMock(
            return_value={establishment_id}
        )
        result = await SurveyService(uow).get(survey.id, field_worker_actor)
        assert result.id == survey.id

    async def test_field_worker_targeted_survey_without_access_forbidden(
        self, make_uow, make_survey, field_worker_actor
    ):
        survey = make_survey(
            scope=SurveyScope.TARGETED,
            establishments=[MagicMock(id=uuid.uuid4())],
        )
        uow = make_uow(survey=survey)
        with pytest.raises(ForbiddenError):
            await SurveyService(uow).get(survey.id, field_worker_actor)

    async def test_field_worker_targeted_survey_with_pending_access_forbidden(
        self, make_uow, make_survey, field_worker_actor
    ):
        establishment_id = uuid.uuid4()
        survey = make_survey(
            scope=SurveyScope.TARGETED,
            establishments=[MagicMock(id=establishment_id)],
        )
        uow = make_uow(survey=survey)
        uow.user_establishment_repo.get_approved_establishment_ids = AsyncMock(
            return_value=set()
        )
        with pytest.raises(ForbiddenError):
            await SurveyService(uow).get(survey.id, field_worker_actor)

    async def test_field_worker_inactive_generic_survey_forbidden(
        self, make_uow, make_survey, field_worker_actor
    ):
        survey = make_survey(scope=SurveyScope.GENERIC, is_active=False)
        uow = make_uow(survey=survey)
        with pytest.raises(ForbiddenError):
            await SurveyService(uow).get(survey.id, field_worker_actor)
        uow.user_establishment_repo.get_approved_establishment_ids.assert_not_called()

    async def test_field_worker_inactive_targeted_survey_with_access_forbidden(
        self, make_uow, make_survey, field_worker_actor
    ):
        establishment_id = uuid.uuid4()
        survey = make_survey(
            scope=SurveyScope.TARGETED,
            establishments=[MagicMock(id=establishment_id)],
            is_active=False,
        )
        uow = make_uow(survey=survey)
        uow.user_establishment_repo.get_approved_establishment_ids = AsyncMock(
            return_value={establishment_id}
        )
        with pytest.raises(ForbiddenError):
            await SurveyService(uow).get(survey.id, field_worker_actor)

    async def test_admin_can_view_inactive_survey(
        self, make_uow, make_survey, admin_actor
    ):
        survey = make_survey(is_active=False)
        uow = make_uow(survey=survey)
        result = await SurveyService(uow).get(survey.id, admin_actor)
        assert result.id == survey.id


class TestList:
    pytestmark = pytest.mark.asyncio

    async def test_passes_offset_and_returns_paginated(self, make_uow, make_survey):
        uow = make_uow()
        uow.survey_repo.list = AsyncMock(return_value=([(make_survey(), 3)], 1))
        result = await SurveyService(uow).list_surveys(
            page=3, page_size=10, params=SurveyListingParams()
        )
        assert isinstance(result, PaginatedResult)
        assert result.items[0].question_count == 3
        uow.survey_repo.list.assert_awaited_once()
        _, kwargs = uow.survey_repo.list.call_args
        assert kwargs["limit"] == 10
        assert kwargs["offset"] == 20


class TestUpdatePermissionsAndLock:
    pytestmark = pytest.mark.asyncio

    async def test_missing_raises(self, make_uow):
        uow = make_uow(survey=None)
        with pytest.raises(SurveyNotFoundError):
            await SurveyService(uow).update(uuid.uuid4(), make_update(), MagicMock())

    async def test_analyst_non_owner_forbidden(
        self, make_uow, make_survey, analyst_actor
    ):
        survey = make_survey(created_by_id=uuid.uuid4())
        uow = make_uow(survey=survey)
        with pytest.raises(ForbiddenError):
            await SurveyService(uow).update(survey.id, make_update(), analyst_actor)
        uow.commit.assert_not_called()

    async def test_analyst_owner_allowed(self, make_uow, make_survey, analyst_actor):
        survey = make_survey(created_by_id=analyst_actor.user_id)
        uow = make_uow(survey=survey)
        result = await SurveyService(uow).update(
            survey.id, make_update(), analyst_actor
        )
        assert isinstance(result, SurveyDomain)
        uow.commit.assert_called_once()

    async def test_admin_edits_any(self, make_uow, make_survey, admin_actor):
        survey = make_survey(created_by_id=uuid.uuid4())
        uow = make_uow(survey=survey)
        await SurveyService(uow).update(survey.id, make_update(), admin_actor)
        uow.survey_repo.reconcile.assert_awaited_once()

    async def test_deleted_question_locked(self, make_uow, make_survey, admin_actor):
        existing = _existing_question()
        survey = make_survey(response_count=1, questions=[existing])
        uow = make_uow(survey=survey)
        data = make_update(questions=[])
        with pytest.raises(SurveyLockedError):
            await SurveyService(uow).update(survey.id, data, admin_actor)
        uow.survey_repo.reconcile.assert_not_called()

    async def test_changed_response_type_locked(
        self, make_uow, make_survey, admin_actor
    ):
        existing = _existing_question(response_type=ResponseType.TEXT)
        survey = make_survey(response_count=1, questions=[existing])
        uow = make_uow(survey=survey)
        data = make_update(
            questions=[
                QuestionInput(
                    id=existing.id,
                    text="Editada",
                    response_type=ResponseType.NUMERIC,
                    is_required=False,
                    options=[],
                )
            ]
        )
        with pytest.raises(SurveyLockedError):
            await SurveyService(uow).update(survey.id, data, admin_actor)
        uow.survey_repo.reconcile.assert_not_called()

    async def test_optional_to_required_locked(
        self, make_uow, make_survey, admin_actor
    ):
        existing = _existing_question(is_required=False)
        survey = make_survey(response_count=1, questions=[existing])
        uow = make_uow(survey=survey)
        data = make_update(
            questions=[
                QuestionInput(
                    id=existing.id,
                    text="Editada",
                    response_type=ResponseType.TEXT,
                    is_required=True,
                    options=[],
                )
            ]
        )
        with pytest.raises(SurveyLockedError):
            await SurveyService(uow).update(survey.id, data, admin_actor)
        uow.survey_repo.reconcile.assert_not_called()

    async def test_removed_referenced_option_locked(
        self, make_uow, make_survey, admin_actor
    ):
        kept_id, removed_id = uuid.uuid4(), uuid.uuid4()
        existing = _existing_question(
            is_required=True,
            response_type=ResponseType.SINGLE_CHOICE,
            option_ids=[kept_id, removed_id],
        )
        survey = make_survey(response_count=1, questions=[existing])
        uow = make_uow(survey=survey, option_referenced=True)
        data = make_update(
            questions=[
                QuestionInput(
                    id=existing.id,
                    text="Editada",
                    response_type=ResponseType.SINGLE_CHOICE,
                    is_required=True,
                    options=[OptionInput(id=kept_id, text="Opción")],
                )
            ]
        )
        with pytest.raises(SurveyLockedError):
            await SurveyService(uow).update(survey.id, data, admin_actor)
        uow.survey_response_repo.get_referenced_option_ids.assert_awaited_once_with(
            survey.id, [(existing.id, removed_id)]
        )
        uow.survey_repo.reconcile.assert_not_called()

    async def test_removed_unreferenced_option_allowed_once_locked(
        self, make_uow, make_survey, admin_actor
    ):
        kept_id, removed_id = uuid.uuid4(), uuid.uuid4()
        existing = _existing_question(
            is_required=True,
            response_type=ResponseType.SINGLE_CHOICE,
            option_ids=[kept_id, removed_id],
        )
        survey = make_survey(response_count=1, questions=[existing])
        uow = make_uow(survey=survey, option_referenced=False)
        data = make_update(
            questions=[
                QuestionInput(
                    id=existing.id,
                    text="Editada",
                    response_type=ResponseType.SINGLE_CHOICE,
                    is_required=True,
                    options=[
                        OptionInput(id=kept_id, text="Opción"),
                        OptionInput(text="Nueva opción"),
                    ],
                )
            ]
        )
        result = await SurveyService(uow).update(survey.id, data, admin_actor)
        assert isinstance(result, SurveyDomain)
        uow.survey_repo.reconcile.assert_awaited_once()

    async def test_rename_allowed_once_locked(self, make_uow, make_survey, admin_actor):
        existing = _existing_question()
        survey = make_survey(response_count=1, questions=[existing])
        uow = make_uow(survey=survey)
        data = make_update(
            questions=[
                QuestionInput(
                    id=existing.id,
                    text="Nuevo texto",
                    response_type=ResponseType.TEXT,
                    is_required=False,
                    options=[],
                )
            ]
        )
        result = await SurveyService(uow).update(survey.id, data, admin_actor)
        assert isinstance(result, SurveyDomain)
        uow.survey_repo.reconcile.assert_awaited_once()

    async def test_reorder_allowed_once_locked(
        self, make_uow, make_survey, admin_actor
    ):
        first = _existing_question()
        second = _existing_question()
        survey = make_survey(response_count=1, questions=[first, second])
        uow = make_uow(survey=survey)
        data = make_update(
            questions=[
                QuestionInput(
                    id=second.id,
                    text="Segunda",
                    response_type=ResponseType.TEXT,
                    is_required=False,
                    options=[],
                ),
                QuestionInput(
                    id=first.id,
                    text="Primera",
                    response_type=ResponseType.TEXT,
                    is_required=False,
                    options=[],
                ),
            ]
        )
        result = await SurveyService(uow).update(survey.id, data, admin_actor)
        assert isinstance(result, SurveyDomain)
        uow.survey_repo.reconcile.assert_awaited_once()

    async def test_add_optional_question_allowed_once_locked(
        self, make_uow, make_survey, admin_actor
    ):
        existing = _existing_question()
        survey = make_survey(response_count=1, questions=[existing])
        uow = make_uow(survey=survey)
        data = make_update(
            questions=[
                QuestionInput(
                    id=existing.id,
                    text="Editada",
                    response_type=ResponseType.TEXT,
                    is_required=False,
                    options=[],
                ),
                _text_question("Nueva pregunta opcional"),
            ]
        )
        result = await SurveyService(uow).update(survey.id, data, admin_actor)
        assert isinstance(result, SurveyDomain)
        uow.survey_repo.reconcile.assert_awaited_once()

    async def test_rename_conflict_uses_exclude_id(
        self, make_uow, make_survey, admin_actor
    ):
        survey = make_survey()
        uow = make_uow(survey=survey, name_exists=True)
        with pytest.raises(SurveyAlreadyExistsError):
            await SurveyService(uow).update(
                survey.id, make_update(name="Otra"), admin_actor
            )
        _, kwargs = uow.survey_repo.name_exists.call_args
        assert kwargs["exclude_id"] == survey.id

    async def test_reconcile_receives_question_ids(
        self, make_uow, make_survey, admin_actor
    ):
        survey = make_survey()
        uow = make_uow(survey=survey)
        qid = uuid.uuid4()
        data = make_update(
            questions=[
                QuestionInput(
                    id=qid,
                    text="Editada",
                    response_type=ResponseType.TEXT,
                    is_required=False,
                    options=[],
                )
            ]
        )
        await SurveyService(uow).update(survey.id, data, admin_actor)
        _, kwargs = uow.survey_repo.reconcile.call_args
        assert kwargs["questions"][0].id == qid


class TestDuplicate:
    pytestmark = pytest.mark.asyncio

    async def test_missing_raises(self, make_uow):
        uow = make_uow(survey=None)
        with pytest.raises(SurveyNotFoundError):
            await SurveyService(uow).duplicate(uuid.uuid4(), MagicMock())

    async def test_first_copy_name(self, make_uow, make_survey, admin_actor):
        survey = make_survey(name="Encuesta A")
        uow = make_uow(survey=survey, name_exists=False)
        await SurveyService(uow).duplicate(survey.id, admin_actor)
        _, kwargs = uow.survey_repo.duplicate.call_args
        assert kwargs["new_name"] == "Encuesta A (copy)"

    async def test_copy_name_collision_bumps_suffix(
        self, make_uow, make_survey, admin_actor
    ):
        survey = make_survey(name="Encuesta A")
        uow = make_uow(survey=survey)
        # "(copy)" taken, "(copy 2)" free.
        uow.survey_repo.name_exists = AsyncMock(side_effect=[True, False])
        await SurveyService(uow).duplicate(survey.id, admin_actor)
        _, kwargs = uow.survey_repo.duplicate.call_args
        assert kwargs["new_name"] == "Encuesta A (copy 2)"

    async def test_field_worker_forbidden(
        self, make_uow, make_survey, field_worker_actor
    ):
        survey = make_survey()
        uow = make_uow(survey=survey)
        with pytest.raises(ForbiddenError):
            await SurveyService(uow).duplicate(survey.id, field_worker_actor)

    async def test_unique_constraint_race_maps_to_conflict(
        self, make_uow, make_survey, admin_actor
    ):
        survey = make_survey(name="Encuesta A")
        uow = make_uow(survey=survey, name_exists=False)
        uow.survey_repo.duplicate = AsyncMock(
            side_effect=UniqueConstraintError("name", "Encuesta A (copy)")
        )
        with pytest.raises(SurveyAlreadyExistsError):
            await SurveyService(uow).duplicate(survey.id, admin_actor)
        uow.commit.assert_not_called()


class TestDelete:
    pytestmark = pytest.mark.asyncio

    async def test_missing_raises(self, make_uow):
        uow = make_uow(survey=None)
        with pytest.raises(SurveyNotFoundError):
            await SurveyService(uow).delete(uuid.uuid4(), MagicMock())

    async def test_locked_survey_rejected(self, make_uow, make_survey, admin_actor):
        survey = make_survey(response_count=3)
        uow = make_uow(survey=survey)
        with pytest.raises(SurveyLockedError):
            await SurveyService(uow).delete(survey.id, admin_actor)
        uow.survey_repo.delete.assert_not_called()

    async def test_non_owner_analyst_forbidden(
        self, make_uow, make_survey, analyst_actor
    ):
        survey = make_survey(created_by_id=uuid.uuid4())
        uow = make_uow(survey=survey)
        with pytest.raises(ForbiddenError):
            await SurveyService(uow).delete(survey.id, analyst_actor)

    async def test_owner_deletes_and_commits(
        self, make_uow, make_survey, analyst_actor
    ):
        survey = make_survey(created_by_id=analyst_actor.user_id)
        uow = make_uow(survey=survey)
        await SurveyService(uow).delete(survey.id, analyst_actor)
        uow.survey_repo.delete.assert_awaited_once_with(survey)
        uow.commit.assert_called_once()


class TestSetActive:
    pytestmark = pytest.mark.asyncio

    async def test_toggle_bypasses_lock(self, make_uow, make_survey, admin_actor):
        survey = make_survey(response_count=99, is_active=True)
        uow = make_uow(survey=survey)
        await SurveyService(uow).set_active(survey.id, False, admin_actor)
        uow.survey_repo.update_active.assert_awaited_once_with(survey, False)
        uow.commit.assert_called_once()

    async def test_non_owner_analyst_forbidden(
        self, make_uow, make_survey, analyst_actor
    ):
        survey = make_survey(created_by_id=uuid.uuid4())
        uow = make_uow(survey=survey)
        with pytest.raises(ForbiddenError):
            await SurveyService(uow).set_active(survey.id, False, analyst_actor)
