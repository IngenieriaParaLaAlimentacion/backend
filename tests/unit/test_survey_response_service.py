import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.establishment import UserEstablishmentStatus
from app.domain.survey import ResponseType, SurveyInstrumentType, SurveyScope
from app.domain.survey_response import SurveyResponseDomain, SurveyResponseListingParams
from app.domain.user import UserActor, UserRole
from app.exceptions.domain_exceptions import (
    EstablishmentNotFoundError,
    ForbiddenError,
    InvalidSurveyResponseError,
    SurveyNotFoundError,
    SurveyResponseNotFoundError,
    UniqueConstraintError,
)
from app.schemas.survey_response_schema import (
    SurveyResponseEditRequest,
    SurveyResponseRequest,
)
from app.services.survey_response_service import SurveyResponseService

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)

# -- Builders --


def _make_option(text: str = "Opción") -> MagicMock:
    o = MagicMock()
    o.id = uuid.uuid4()
    o.text = text
    o.position = 0
    return o


def _make_question(
    response_type: ResponseType = ResponseType.TEXT,
    is_required: bool = False,
    options: list | None = None,
) -> MagicMock:
    q = MagicMock()
    q.id = uuid.uuid4()
    q.text = "¿Pregunta?"
    q.response_type = response_type
    q.is_required = is_required
    q.position = 0
    q.options = options or []
    return q


def _make_survey_orm(
    scope: SurveyScope = SurveyScope.GENERIC,
    questions: list | None = None,
    establishment_ids: list[uuid.UUID] | None = None,
) -> MagicMock:
    """A MagicMock standing in for an ORM Survey with eager-loaded relations."""
    s = MagicMock()
    s.id = uuid.uuid4()
    s.name = "Encuesta"
    s.description = None
    s.scope = scope
    s.created_by_id = uuid.uuid4()
    s.is_active = True
    s.response_count = 0
    s.questions = questions or []
    establishments = []
    for establishment_id in establishment_ids or []:
        e = MagicMock()
        e.id = establishment_id
        establishments.append(e)
    s.establishments = establishments
    s.created_at = NOW
    s.updated_at = NOW
    return s


def _make_response(
    survey_id: uuid.UUID | None = None,
    establishment_id: uuid.UUID | None = None,
    submitted_by_id: uuid.UUID | None = None,
    answers: dict | None = None,
    event_at: datetime = NOW,
) -> MagicMock:
    """A MagicMock standing in for an ORM SurveyResponse."""
    r = MagicMock()
    r.id = uuid.uuid4()
    r.survey_id = survey_id or uuid.uuid4()
    r.establishment_id = establishment_id or uuid.uuid4()
    r.submitted_by_id = submitted_by_id or uuid.uuid4()
    r.answers = answers if answers is not None else {}
    r.event_at = event_at
    r.created_at = NOW
    r.updated_at = NOW
    return r


def _make_fies_survey_orm(num_questions: int = 8) -> tuple[MagicMock, list[MagicMock]]:
    """A FIES-marked survey ORM double with `num_questions` dichotomous
    single_choice questions: option[0]="Sí" (affirmative, position 0),
    option[1]="No" (position 1)."""
    questions = []
    for i in range(num_questions):
        yes = _make_option("Sí")
        yes.position = 0
        no = _make_option("No")
        no.position = 1
        q = _make_question(
            response_type=ResponseType.SINGLE_CHOICE,
            is_required=True,
            options=[yes, no],
        )
        q.position = i
        questions.append(q)
    survey = _make_survey_orm(questions=questions)
    survey.instrument_type = SurveyInstrumentType.FIES
    return survey, questions


def _apply_update_answers(response, answers, score_fies, event_at):
    response.answers = answers
    response.score_fies = score_fies
    response.event_at = event_at
    return response


# -- Fixtures --

_UNSET = object()


@pytest.fixture
def make_uow():
    def _make(
        survey=None,
        establishment=_UNSET,
        relation=None,
        existing_response=None,
        created_response=None,
        existing_edit=None,
    ):
        uow = AsyncMock()
        uow.survey_repo.get_by_id = AsyncMock(return_value=survey)
        uow.establishment_repo.get_by_id = AsyncMock(
            return_value=MagicMock() if establishment is _UNSET else establishment
        )
        uow.user_establishment_repo.get_relation = AsyncMock(return_value=relation)
        uow.survey_response_repo.get_by_id = AsyncMock(return_value=existing_response)
        uow.survey_response_repo.create = AsyncMock(
            return_value=created_response or _make_response()
        )
        uow.survey_response_repo.update_answers = AsyncMock(
            side_effect=_apply_update_answers
        )
        uow.survey_response_edit_repo.get_by_id = AsyncMock(return_value=existing_edit)
        uow.survey_response_edit_repo.create = AsyncMock()
        uow.survey_repo.increment_response_count = AsyncMock()
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


class TestValidateAnswers:
    def test_required_missing_rejected(self):
        q = _make_question(is_required=True)
        with pytest.raises(InvalidSurveyResponseError):
            SurveyResponseService._validate_answers([q], {})

    def test_optional_left_unanswered_allowed(self):
        q = _make_question(is_required=False)
        result = SurveyResponseService._validate_answers([q], {})
        assert result == {}

    def test_unknown_question_id_rejected(self):
        q = _make_question()
        with pytest.raises(InvalidSurveyResponseError):
            SurveyResponseService._validate_answers([q], {str(uuid.uuid4()): "x"})

    def test_text_accepts_any_string(self):
        q = _make_question(response_type=ResponseType.TEXT, is_required=True)
        result = SurveyResponseService._validate_answers(
            [q], {str(q.id): "respuesta libre"}
        )
        assert result[str(q.id)] == "respuesta libre"

    def test_date_accepted_as_opaque_string(self):
        q = _make_question(response_type=ResponseType.DATE, is_required=True)
        result = SurveyResponseService._validate_answers([q], {str(q.id): "2026-01-01"})
        assert result[str(q.id)] == "2026-01-01"

    def test_numeric_wrong_shape_rejected(self):
        q = _make_question(response_type=ResponseType.NUMERIC)
        with pytest.raises(InvalidSurveyResponseError):
            SurveyResponseService._validate_answers([q], {str(q.id): "not-a-number"})

    def test_numeric_accepts_number(self):
        q = _make_question(response_type=ResponseType.NUMERIC)
        result = SurveyResponseService._validate_answers([q], {str(q.id): 3})
        assert result[str(q.id)] == 3

    def test_single_choice_unknown_option_id_rejected(self):
        option = _make_option()
        q = _make_question(response_type=ResponseType.SINGLE_CHOICE, options=[option])
        with pytest.raises(InvalidSurveyResponseError):
            SurveyResponseService._validate_answers([q], {str(q.id): str(uuid.uuid4())})

    def test_single_choice_valid_option_accepted(self):
        option = _make_option()
        q = _make_question(response_type=ResponseType.SINGLE_CHOICE, options=[option])
        result = SurveyResponseService._validate_answers(
            [q], {str(q.id): str(option.id)}
        )
        assert result[str(q.id)] == str(option.id)

    def test_multiple_choice_unknown_option_id_rejected(self):
        option = _make_option()
        q = _make_question(response_type=ResponseType.MULTIPLE_CHOICE, options=[option])
        with pytest.raises(InvalidSurveyResponseError):
            SurveyResponseService._validate_answers(
                [q], {str(q.id): [str(uuid.uuid4())]}
            )

    def test_multiple_choice_valid_options_accepted(self):
        option = _make_option()
        q = _make_question(response_type=ResponseType.MULTIPLE_CHOICE, options=[option])
        result = SurveyResponseService._validate_answers(
            [q], {str(q.id): [str(option.id)]}
        )
        assert result[str(q.id)] == [str(option.id)]


class TestSubmit:
    pytestmark = pytest.mark.asyncio

    @pytest.fixture
    def request_factory(self):
        def _make(**overrides):
            data = dict(
                survey_id=uuid.uuid4(),
                establishment_id=uuid.uuid4(),
                answers={},
                event_at=NOW,
            )
            data.update(overrides)
            return SurveyResponseRequest(**data)

        return _make

    async def test_analyst_forbidden(self, make_uow, request_factory, analyst_actor):
        survey = _make_survey_orm()
        uow = make_uow(survey=survey)
        data = request_factory(survey_id=survey.id)
        with pytest.raises(ForbiddenError):
            await SurveyResponseService(uow).submit(data, analyst_actor)
        uow.commit.assert_not_called()

    async def test_field_worker_without_access_forbidden(
        self, make_uow, request_factory, field_worker_actor
    ):
        survey = _make_survey_orm()
        uow = make_uow(survey=survey, relation=None)
        data = request_factory(survey_id=survey.id)
        with pytest.raises(ForbiddenError):
            await SurveyResponseService(uow).submit(data, field_worker_actor)
        uow.commit.assert_not_called()

    async def test_field_worker_with_approved_access_allowed(
        self, make_uow, request_factory, field_worker_actor
    ):
        survey = _make_survey_orm()
        relation = MagicMock(status=UserEstablishmentStatus.APPROVED)
        uow = make_uow(survey=survey, relation=relation)
        data = request_factory(survey_id=survey.id)
        response, created = await SurveyResponseService(uow).submit(
            data, field_worker_actor
        )
        assert created is True
        assert isinstance(response, SurveyResponseDomain)
        uow.commit.assert_called_once()

    async def test_survey_not_found(self, make_uow, request_factory, admin_actor):
        uow = make_uow(survey=None)
        data = request_factory()
        with pytest.raises(SurveyNotFoundError):
            await SurveyResponseService(uow).submit(data, admin_actor)

    async def test_establishment_not_found(
        self, make_uow, request_factory, admin_actor
    ):
        survey = _make_survey_orm()
        uow = make_uow(survey=survey, establishment=None)
        data = request_factory(survey_id=survey.id)
        with pytest.raises(EstablishmentNotFoundError):
            await SurveyResponseService(uow).submit(data, admin_actor)

    async def test_admin_outside_targeted_audience_rejected(
        self, make_uow, request_factory, admin_actor
    ):
        allowed_id = uuid.uuid4()
        survey = _make_survey_orm(
            scope=SurveyScope.TARGETED, establishment_ids=[allowed_id]
        )
        uow = make_uow(survey=survey)
        data = request_factory(survey_id=survey.id, establishment_id=uuid.uuid4())
        with pytest.raises(InvalidSurveyResponseError):
            await SurveyResponseService(uow).submit(data, admin_actor)

    async def test_required_question_missing_rejected_no_partial_save(
        self, make_uow, request_factory, admin_actor
    ):
        question = _make_question(is_required=True)
        survey = _make_survey_orm(questions=[question])
        uow = make_uow(survey=survey)
        data = request_factory(survey_id=survey.id, answers={})
        with pytest.raises(InvalidSurveyResponseError):
            await SurveyResponseService(uow).submit(data, admin_actor)
        uow.survey_response_repo.create.assert_not_called()
        uow.commit.assert_not_called()

    async def test_success_increments_response_count_and_commits(
        self, make_uow, request_factory, admin_actor
    ):
        survey = _make_survey_orm()
        uow = make_uow(survey=survey)
        data = request_factory(survey_id=survey.id)
        response, created = await SurveyResponseService(uow).submit(data, admin_actor)
        assert created is True
        uow.survey_repo.increment_response_count.assert_awaited_once_with(survey.id)
        uow.commit.assert_called_once()

    async def test_replayed_id_returns_existing_for_authorized_actor(
        self, make_uow, request_factory, admin_actor
    ):
        existing = _make_response()
        uow = make_uow(existing_response=existing)
        data = request_factory(id=existing.id)
        response, created = await SurveyResponseService(uow).submit(data, admin_actor)
        assert created is False
        assert response.id == existing.id
        uow.survey_response_repo.create.assert_not_called()
        uow.commit.assert_not_called()

    async def test_replayed_id_still_forbidden_for_disallowed_role(
        self, make_uow, request_factory, analyst_actor
    ):
        existing = _make_response()
        uow = make_uow(existing_response=existing)
        data = request_factory(id=existing.id)
        with pytest.raises(ForbiddenError):
            await SurveyResponseService(uow).submit(data, analyst_actor)
        uow.survey_response_repo.create.assert_not_called()

    async def test_replayed_id_still_checks_establishment_access(
        self, make_uow, request_factory, field_worker_actor
    ):
        """Knowing a response's id must not bypass the establishment-access
        check: the field worker isn't related to the *existing* response's
        establishment, even though relation=None wouldn't matter for the
        (unused) payload establishment_id."""
        existing = _make_response()
        uow = make_uow(existing_response=existing, relation=None)
        data = request_factory(id=existing.id)
        with pytest.raises(ForbiddenError):
            await SurveyResponseService(uow).submit(data, field_worker_actor)
        uow.survey_response_repo.create.assert_not_called()

    async def test_race_on_create_returns_existing(
        self, make_uow, request_factory, admin_actor
    ):
        survey = _make_survey_orm()
        response_id = uuid.uuid4()
        existing = _make_response()
        existing.id = response_id
        uow = make_uow(survey=survey)
        uow.survey_response_repo.get_by_id = AsyncMock(side_effect=[None, existing])
        uow.survey_response_repo.create = AsyncMock(
            side_effect=UniqueConstraintError("id", response_id)
        )
        data = request_factory(id=response_id, survey_id=survey.id)
        response, created = await SurveyResponseService(uow).submit(data, admin_actor)
        assert created is False
        assert response.id == response_id
        uow.commit.assert_not_called()


class TestGet:
    pytestmark = pytest.mark.asyncio

    async def test_response_not_found(self, make_uow, admin_actor):
        uow = make_uow(existing_response=None)
        with pytest.raises(SurveyResponseNotFoundError):
            await SurveyResponseService(uow).get(uuid.uuid4(), admin_actor)

    async def test_owner_field_worker_allowed(self, make_uow):
        actor = UserActor(user_id=uuid.uuid4(), role=UserRole.FIELD_WORKER)
        response = _make_response(submitted_by_id=actor.user_id, answers={"a": "b"})
        uow = make_uow(existing_response=response)
        result = await SurveyResponseService(uow).get(response.id, actor)
        assert isinstance(result, SurveyResponseDomain)
        assert result.answers == {"a": "b"}

    async def test_non_owner_field_worker_forbidden(self, make_uow, field_worker_actor):
        response = _make_response(submitted_by_id=uuid.uuid4())
        uow = make_uow(existing_response=response)
        with pytest.raises(ForbiddenError):
            await SurveyResponseService(uow).get(response.id, field_worker_actor)

    async def test_admin_can_view_any_response(self, make_uow, admin_actor):
        response = _make_response(submitted_by_id=uuid.uuid4())
        uow = make_uow(existing_response=response)
        result = await SurveyResponseService(uow).get(response.id, admin_actor)
        assert result.id == response.id

    async def test_superadmin_can_view_any_response(self, make_uow):
        actor = UserActor(user_id=uuid.uuid4(), role=UserRole.SUPERADMIN)
        response = _make_response(submitted_by_id=uuid.uuid4())
        uow = make_uow(existing_response=response)
        result = await SurveyResponseService(uow).get(response.id, actor)
        assert result.id == response.id

    async def test_analyst_forbidden_for_someone_elses_response(
        self, make_uow, analyst_actor
    ):
        response = _make_response(submitted_by_id=uuid.uuid4())
        uow = make_uow(existing_response=response)
        with pytest.raises(ForbiddenError):
            await SurveyResponseService(uow).get(response.id, analyst_actor)


class TestEdit:
    pytestmark = pytest.mark.asyncio

    @pytest.fixture
    def edit_factory(self):
        def _make(**overrides):
            data = dict(answers={}, event_at=NOW)
            data.update(overrides)
            return SurveyResponseEditRequest(**data)

        return _make

    async def test_response_not_found(self, make_uow, edit_factory, admin_actor):
        uow = make_uow(existing_response=None)
        with pytest.raises(SurveyResponseNotFoundError):
            await SurveyResponseService(uow).edit(
                uuid.uuid4(), edit_factory(), admin_actor
            )

    async def test_non_owner_field_worker_forbidden(
        self, make_uow, edit_factory, field_worker_actor
    ):
        response = _make_response(submitted_by_id=uuid.uuid4())
        survey = _make_survey_orm()
        response.survey_id = survey.id
        uow = make_uow(survey=survey, existing_response=response)
        with pytest.raises(ForbiddenError):
            await SurveyResponseService(uow).edit(
                response.id, edit_factory(), field_worker_actor
            )
        uow.survey_response_edit_repo.create.assert_not_called()

    async def test_owner_field_worker_allowed(self, make_uow, edit_factory):
        actor = UserActor(user_id=uuid.uuid4(), role=UserRole.FIELD_WORKER)
        response = _make_response(submitted_by_id=actor.user_id)
        survey = _make_survey_orm()
        response.survey_id = survey.id
        uow = make_uow(survey=survey, existing_response=response)
        result = await SurveyResponseService(uow).edit(
            response.id, edit_factory(), actor
        )
        assert isinstance(result, SurveyResponseDomain)
        uow.commit.assert_called_once()

    async def test_admin_override_allowed(self, make_uow, edit_factory, admin_actor):
        response = _make_response(submitted_by_id=uuid.uuid4())
        survey = _make_survey_orm()
        response.survey_id = survey.id
        uow = make_uow(survey=survey, existing_response=response)
        result = await SurveyResponseService(uow).edit(
            response.id, edit_factory(), admin_actor
        )
        assert isinstance(result, SurveyResponseDomain)

    async def test_replayed_edit_id_returns_unchanged(
        self, make_uow, edit_factory, admin_actor
    ):
        response = _make_response()
        existing_edit = MagicMock()
        uow = make_uow(existing_response=response, existing_edit=existing_edit)
        result = await SurveyResponseService(uow).edit(
            response.id, edit_factory(id=uuid.uuid4()), admin_actor
        )
        assert result.id == response.id
        uow.survey_response_edit_repo.create.assert_not_called()
        uow.commit.assert_not_called()

    async def test_newer_event_at_overwrites_current_state(
        self, make_uow, edit_factory, admin_actor
    ):
        new_time = NOW + timedelta(hours=1)
        response = _make_response(event_at=NOW, answers={"a": "old"})
        survey = _make_survey_orm()
        response.survey_id = survey.id
        uow = make_uow(survey=survey, existing_response=response)
        result = await SurveyResponseService(uow).edit(
            response.id, edit_factory(answers={}, event_at=new_time), admin_actor
        )
        uow.survey_response_repo.update_answers.assert_awaited_once()
        assert result.event_at == new_time

    async def test_older_event_at_logged_but_does_not_overwrite(
        self, make_uow, edit_factory, admin_actor
    ):
        older_time = NOW - timedelta(hours=1)
        response = _make_response(event_at=NOW, answers={"a": "current"})
        survey = _make_survey_orm()
        response.survey_id = survey.id
        uow = make_uow(survey=survey, existing_response=response)
        result = await SurveyResponseService(uow).edit(
            response.id, edit_factory(answers={}, event_at=older_time), admin_actor
        )
        uow.survey_response_edit_repo.create.assert_awaited_once()
        uow.survey_response_repo.update_answers.assert_not_called()
        assert result.event_at == NOW
        assert result.answers == {"a": "current"}
        uow.commit.assert_called_once()

    async def test_required_question_missing_rejected(
        self, make_uow, edit_factory, admin_actor
    ):
        question = _make_question(is_required=True)
        survey = _make_survey_orm(questions=[question])
        response = _make_response()
        response.survey_id = survey.id
        uow = make_uow(survey=survey, existing_response=response)
        with pytest.raises(InvalidSurveyResponseError):
            await SurveyResponseService(uow).edit(
                response.id, edit_factory(answers={}), admin_actor
            )
        uow.survey_response_edit_repo.create.assert_not_called()


class TestListBySurvey:
    pytestmark = pytest.mark.asyncio

    async def test_admin_gets_paginated_result(self, make_uow, admin_actor):
        survey = _make_survey_orm()
        response = _make_response(survey_id=survey.id)
        uow = make_uow(survey=survey)
        uow.survey_response_repo.list_by_survey = AsyncMock(
            return_value=([response], 1)
        )

        result = await SurveyResponseService(uow).list_by_survey(
            survey.id,
            admin_actor,
            page=1,
            page_size=20,
            params=SurveyResponseListingParams(),
        )

        assert result.total == 1
        assert len(result.items) == 1
        assert result.items[0].id == response.id
        uow.survey_response_repo.list_by_survey.assert_awaited_once_with(
            survey.id, limit=20, offset=0, params=SurveyResponseListingParams()
        )

    async def test_analyst_can_list(self, make_uow, analyst_actor):
        survey = _make_survey_orm()
        uow = make_uow(survey=survey)
        uow.survey_response_repo.list_by_survey = AsyncMock(return_value=([], 0))

        result = await SurveyResponseService(uow).list_by_survey(
            survey.id,
            analyst_actor,
            page=1,
            page_size=20,
            params=SurveyResponseListingParams(),
        )

        assert result.total == 0

    async def test_field_worker_forbidden(self, make_uow, field_worker_actor):
        survey = _make_survey_orm()
        uow = make_uow(survey=survey)
        uow.survey_response_repo.list_by_survey = AsyncMock(return_value=([], 0))

        with pytest.raises(ForbiddenError):
            await SurveyResponseService(uow).list_by_survey(
                survey.id,
                field_worker_actor,
                page=1,
                page_size=20,
                params=SurveyResponseListingParams(),
            )
        uow.survey_repo.get_by_id.assert_not_awaited()
        uow.survey_response_repo.list_by_survey.assert_not_awaited()

    async def test_survey_not_found(self, make_uow, admin_actor):
        uow = make_uow(survey=None)
        uow.survey_response_repo.list_by_survey = AsyncMock(return_value=([], 0))

        with pytest.raises(SurveyNotFoundError):
            await SurveyResponseService(uow).list_by_survey(
                uuid.uuid4(),
                admin_actor,
                page=1,
                page_size=20,
                params=SurveyResponseListingParams(),
            )
        uow.survey_response_repo.list_by_survey.assert_not_awaited()

    async def test_computes_offset_from_page(self, make_uow, admin_actor):
        survey = _make_survey_orm()
        uow = make_uow(survey=survey)
        uow.survey_response_repo.list_by_survey = AsyncMock(return_value=([], 0))

        await SurveyResponseService(uow).list_by_survey(
            survey.id,
            admin_actor,
            page=3,
            page_size=10,
            params=SurveyResponseListingParams(),
        )

        uow.survey_response_repo.list_by_survey.assert_awaited_once_with(
            survey.id, limit=10, offset=20, params=SurveyResponseListingParams()
        )

    async def test_clamps_page_below_one(self, make_uow, admin_actor):
        survey = _make_survey_orm()
        uow = make_uow(survey=survey)
        uow.survey_response_repo.list_by_survey = AsyncMock(return_value=([], 0))

        await SurveyResponseService(uow).list_by_survey(
            survey.id,
            admin_actor,
            page=0,
            page_size=10,
            params=SurveyResponseListingParams(),
        )

        uow.survey_response_repo.list_by_survey.assert_awaited_once_with(
            survey.id, limit=10, offset=0, params=SurveyResponseListingParams()
        )


def _make_response_with_detail(
    questions: list,
    answers: dict,
    submitted_by_id: uuid.UUID | None = None,
    submitted_by_name: str = "Juana Pérez",
) -> MagicMock:
    survey = MagicMock()
    survey.id = uuid.uuid4()
    survey.name = "Encuesta FIES"
    survey.questions = questions

    establishment = MagicMock()
    establishment.id = uuid.uuid4()

    submitter = MagicMock()
    submitter.id = submitted_by_id or uuid.uuid4()
    submitter.name = submitted_by_name

    r = MagicMock()
    r.id = uuid.uuid4()
    r.event_at = NOW
    r.answers = answers
    r.survey = survey
    r.establishment = establishment
    r.submitted_by = submitter
    return r


class TestGetDashboardDetail:
    pytestmark = pytest.mark.asyncio

    async def test_admin_gets_full_detail_with_resolved_labels(
        self, make_uow, admin_actor
    ):
        option_yes = _make_option("Sí")
        option_no = _make_option("No")
        choice_question = _make_question(
            response_type=ResponseType.SINGLE_CHOICE, options=[option_yes, option_no]
        )
        choice_question.position = 0
        text_question = _make_question(response_type=ResponseType.TEXT)
        text_question.position = 1

        response = _make_response_with_detail(
            questions=[text_question, choice_question],
            answers={
                str(choice_question.id): str(option_yes.id),
                str(text_question.id): "Todo bien",
            },
        )
        uow = make_uow()
        uow.survey_response_repo.get_with_relations = AsyncMock(return_value=response)

        result = await SurveyResponseService(uow).get_response_detail(
            response.id, admin_actor
        )

        assert [a.question_id for a in result.answers] == [
            choice_question.id,
            text_question.id,
        ]
        choice_answer, text_answer = result.answers
        assert text_answer.value == "Todo bien"
        assert text_answer.value_label is None
        assert choice_answer.value_label == "Sí"
        assert result.submitted_by.name == "Juana Pérez"

    async def test_multiple_choice_resolves_all_labels(self, make_uow, admin_actor):
        option_a = _make_option("Verduras")
        option_b = _make_option("Frutas")
        question = _make_question(
            response_type=ResponseType.MULTIPLE_CHOICE, options=[option_a, option_b]
        )
        response = _make_response_with_detail(
            questions=[question],
            answers={str(question.id): [str(option_a.id), str(option_b.id)]},
        )
        uow = make_uow()
        uow.survey_response_repo.get_with_relations = AsyncMock(return_value=response)

        result = await SurveyResponseService(uow).get_response_detail(
            response.id, admin_actor
        )

        assert result.answers[0].value_label == ["Verduras", "Frutas"]

    async def test_unanswered_question_has_none_value_and_label(
        self, make_uow, admin_actor
    ):
        question = _make_question(response_type=ResponseType.TEXT, is_required=False)
        response = _make_response_with_detail(questions=[question], answers={})
        uow = make_uow()
        uow.survey_response_repo.get_with_relations = AsyncMock(return_value=response)

        result = await SurveyResponseService(uow).get_response_detail(
            response.id, admin_actor
        )

        assert result.answers[0].value is None
        assert result.answers[0].value_label is None

    async def test_analyst_can_view(self, make_uow, analyst_actor):
        question = _make_question(response_type=ResponseType.TEXT)
        response = _make_response_with_detail(questions=[question], answers={})
        uow = make_uow()
        uow.survey_response_repo.get_with_relations = AsyncMock(return_value=response)

        result = await SurveyResponseService(uow).get_response_detail(
            response.id, analyst_actor
        )
        assert result.id == response.id

    async def test_field_worker_forbidden(self, make_uow, field_worker_actor):
        uow = make_uow()
        uow.survey_response_repo.get_with_relations = AsyncMock()

        with pytest.raises(ForbiddenError):
            await SurveyResponseService(uow).get_response_detail(
                uuid.uuid4(), field_worker_actor
            )
        uow.survey_response_repo.get_with_relations.assert_not_awaited()

    async def test_response_not_found(self, make_uow, admin_actor):
        uow = make_uow()
        uow.survey_response_repo.get_with_relations = AsyncMock(return_value=None)

        with pytest.raises(SurveyResponseNotFoundError):
            await SurveyResponseService(uow).get_response_detail(
                uuid.uuid4(), admin_actor
            )


class TestFiesScoring:
    pytestmark = pytest.mark.asyncio

    @pytest.fixture
    def request_factory(self):
        def _make(**overrides):
            data = dict(
                survey_id=uuid.uuid4(),
                establishment_id=uuid.uuid4(),
                answers={},
                event_at=NOW,
            )
            data.update(overrides)
            return SurveyResponseRequest(**data)

        return _make

    @pytest.fixture
    def edit_factory(self):
        def _make(**overrides):
            data = dict(answers={}, event_at=NOW)
            data.update(overrides)
            return SurveyResponseEditRequest(**data)

        return _make

    async def test_all_affirmative_scores_max(
        self, make_uow, request_factory, admin_actor
    ):
        survey, questions = _make_fies_survey_orm(num_questions=8)
        answers = {str(q.id): str(q.options[0].id) for q in questions}  # all "Sí"
        uow = make_uow(survey=survey)
        data = request_factory(survey_id=survey.id, answers=answers)

        await SurveyResponseService(uow).submit(data, admin_actor)

        create_call = uow.survey_response_repo.create.call_args
        assert create_call.kwargs["score_fies"] == 8

    async def test_all_negative_scores_zero(
        self, make_uow, request_factory, admin_actor
    ):
        survey, questions = _make_fies_survey_orm(num_questions=8)
        answers = {str(q.id): str(q.options[1].id) for q in questions}  # all "No"
        uow = make_uow(survey=survey)
        data = request_factory(survey_id=survey.id, answers=answers)

        await SurveyResponseService(uow).submit(data, admin_actor)

        create_call = uow.survey_response_repo.create.call_args
        assert create_call.kwargs["score_fies"] == 0

    async def test_partial_affirmative_scores_correctly(
        self, make_uow, request_factory, admin_actor
    ):
        survey, questions = _make_fies_survey_orm(num_questions=8)
        answers = {
            str(q.id): str(q.options[0].id if i < 3 else q.options[1].id)
            for i, q in enumerate(questions)
        }
        uow = make_uow(survey=survey)
        data = request_factory(survey_id=survey.id, answers=answers)

        await SurveyResponseService(uow).submit(data, admin_actor)

        create_call = uow.survey_response_repo.create.call_args
        assert create_call.kwargs["score_fies"] == 3

    async def test_custom_survey_has_null_score(
        self, make_uow, request_factory, admin_actor
    ):
        question = _make_question(is_required=False)
        survey = _make_survey_orm(questions=[question])
        survey.instrument_type = SurveyInstrumentType.CUSTOM
        uow = make_uow(survey=survey)
        data = request_factory(survey_id=survey.id, answers={})

        await SurveyResponseService(uow).submit(data, admin_actor)

        create_call = uow.survey_response_repo.create.call_args
        assert create_call.kwargs["score_fies"] is None

    async def test_unanswered_fies_question_not_counted(
        self, make_uow, request_factory, admin_actor
    ):
        survey, questions = _make_fies_survey_orm(num_questions=8)
        questions[0].is_required = False  # allow leaving it unanswered
        answers = {
            str(q.id): str(q.options[0].id) for q in questions[1:]
        }  # first question left unanswered, rest all "Sí"
        uow = make_uow(survey=survey)
        data = request_factory(survey_id=survey.id, answers=answers)

        await SurveyResponseService(uow).submit(data, admin_actor)

        create_call = uow.survey_response_repo.create.call_args
        assert create_call.kwargs["score_fies"] == 7

    async def test_edit_recalculates_score(self, make_uow, edit_factory, admin_actor):
        survey, questions = _make_fies_survey_orm(num_questions=8)
        original_answers = {
            str(q.id): str(q.options[1].id) for q in questions
        }  # all "No"
        response = _make_response(survey_id=survey.id, answers=original_answers)
        uow = make_uow(survey=survey, existing_response=response)

        new_answers = {str(q.id): str(q.options[0].id) for q in questions}  # all "Sí"
        await SurveyResponseService(uow).edit(
            response.id, edit_factory(answers=new_answers, event_at=NOW), admin_actor
        )

        update_call = uow.survey_response_repo.update_answers.call_args
        assert update_call.kwargs["score_fies"] == 8

    async def test_edit_with_older_event_at_does_not_call_update(
        self, make_uow, edit_factory, admin_actor
    ):
        """When the edit is older than the response's current event_at, the
        audit row is still logged but update_answers (and its score
        recalculation) is never applied."""
        survey, questions = _make_fies_survey_orm(num_questions=8)
        original_answers = {str(q.id): str(q.options[1].id) for q in questions}
        response = _make_response(
            survey_id=survey.id, answers=original_answers, event_at=NOW
        )
        uow = make_uow(survey=survey, existing_response=response)
        older_time = NOW - timedelta(hours=1)
        new_answers = {str(q.id): str(q.options[0].id) for q in questions}

        await SurveyResponseService(uow).edit(
            response.id,
            edit_factory(answers=new_answers, event_at=older_time),
            admin_actor,
        )

        uow.survey_response_repo.update_answers.assert_not_called()


class TestSurveyResponseListingParams:
    def test_blank_city_normalizes_to_none(self):
        params = SurveyResponseListingParams(city="   ")
        assert params.city is None

    def test_city_is_stripped(self):
        params = SurveyResponseListingParams(city="  Cordoba  ")
        assert params.city == "Cordoba"

    def test_none_city_stays_none(self):
        params = SurveyResponseListingParams()
        assert params.city is None
        assert params.province is None


class TestListBySurveyFilters:
    pytestmark = pytest.mark.asyncio

    async def test_passes_params_through_to_repo(self, make_uow, admin_actor):
        survey = _make_survey_orm()
        uow = make_uow(survey=survey)
        uow.survey_response_repo.list_by_survey = AsyncMock(return_value=([], 0))
        establishment_id = uuid.uuid4()
        params = SurveyResponseListingParams(
            establishment_id=establishment_id,
            event_at_from=NOW,
            event_at_to=NOW,
            city="Cordoba",
            province="Cordoba",
        )

        await SurveyResponseService(uow).list_by_survey(
            survey.id, admin_actor, page=1, page_size=20, params=params
        )

        uow.survey_response_repo.list_by_survey.assert_awaited_once_with(
            survey.id, limit=20, offset=0, params=params
        )

    async def test_default_params_is_unfiltered(self, make_uow, admin_actor):
        survey = _make_survey_orm()
        uow = make_uow(survey=survey)
        uow.survey_response_repo.list_by_survey = AsyncMock(return_value=([], 0))

        await SurveyResponseService(uow).list_by_survey(
            survey.id,
            admin_actor,
            page=1,
            page_size=20,
            params=SurveyResponseListingParams(),
        )

        call = uow.survey_response_repo.list_by_survey.call_args
        assert call.kwargs["params"].establishment_id is None
        assert call.kwargs["params"].city is None


class TestExport:
    pytestmark = pytest.mark.asyncio

    async def test_admin_can_export(self, make_uow, admin_actor):
        survey = _make_survey_orm()
        uow = make_uow(survey=survey)
        uow.survey_response_repo.list_all_for_export = AsyncMock(return_value=[])
        fake_exporter = MagicMock()
        fake_exporter.export.return_value = b"fake-bytes"

        result = await SurveyResponseService(uow).export(
            survey.id, uuid.uuid4(), admin_actor, fake_exporter
        )

        assert result == b"fake-bytes"
        fake_exporter.export.assert_called_once()

    async def test_field_worker_forbidden(self, make_uow, field_worker_actor):
        survey = _make_survey_orm()
        uow = make_uow(survey=survey)
        fake_exporter = MagicMock()

        with pytest.raises(ForbiddenError):
            await SurveyResponseService(uow).export(
                survey.id, uuid.uuid4(), field_worker_actor, fake_exporter
            )
        fake_exporter.export.assert_not_called()

    async def test_survey_not_found(self, make_uow, admin_actor):
        uow = make_uow(survey=None)
        fake_exporter = MagicMock()

        with pytest.raises(SurveyNotFoundError):
            await SurveyResponseService(uow).export(
                uuid.uuid4(), uuid.uuid4(), admin_actor, fake_exporter
            )

    async def test_filters_by_establishment(self, make_uow, admin_actor):
        survey = _make_survey_orm()
        establishment_id = uuid.uuid4()
        uow = make_uow(survey=survey)
        uow.survey_response_repo.list_all_for_export = AsyncMock(return_value=[])
        fake_exporter = MagicMock()
        fake_exporter.export.return_value = b""

        await SurveyResponseService(uow).export(
            survey.id, establishment_id, admin_actor, fake_exporter
        )

        uow.survey_response_repo.list_all_for_export.assert_awaited_once_with(
            survey.id, establishment_id
        )
