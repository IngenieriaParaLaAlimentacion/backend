import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.survey import (
    ResponseType,
    SurveyResponseTarget,
)
from app.domain.survey_response import (
    SurveyResponseDomain,
)
from app.exceptions.domain_exceptions import (
    EstablishmentNotFoundError,
    ForbiddenError,
    InvalidSurveyResponseError,
    SubjectNotFoundError,
    SurveyNotFoundError,
    SurveyResponseAlreadyExistsError,
    UniqueConstraintError,
)
from app.schemas.surveys.survey_response_schema import (
    SurveyResponseRequest,
)
from app.services.surveys.survey_response_service import SurveyResponseService
from tests.unit.surveys.response_service.helpers import (
    NOW,
    _make_option,
    _make_question,
    _make_response,
    _make_survey_orm,
)


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
    @pytest.fixture
    def request_factory(self):
        def _make(**overrides):
            data = dict(answers={}, response_number=1, event_at=NOW)
            data.update(overrides)
            return SurveyResponseRequest(**data)

        return _make

    @pytest.mark.parametrize("setting", [False, None])
    async def test_optional_survey_accepts_missing_number(
        self, make_uow, request_factory, admin_actor, setting
    ):
        survey = _make_survey_orm(requires_response_number=setting)
        created = _make_response(survey_id=survey.id, response_number=None)
        uow = make_uow(survey=survey, created_response=created)

        result, was_created = await SurveyResponseService(uow).submit(
            survey.id, request_factory(response_number=None), admin_actor
        )

        assert was_created is True
        assert result.response_number is None
        assert (
            uow.survey_response_repo.create.call_args.kwargs["response_number"] is None
        )

    async def test_required_survey_rejects_missing_number_without_persistence(
        self, make_uow, request_factory, admin_actor
    ):
        survey = _make_survey_orm(requires_response_number=True)
        uow = make_uow(survey=survey)

        with pytest.raises(InvalidSurveyResponseError):
            await SurveyResponseService(uow).submit(
                survey.id, request_factory(response_number=None), admin_actor
            )

        uow.survey_response_repo.create.assert_not_called()
        uow.commit.assert_not_called()

    async def test_analyst_forbidden(self, make_uow, request_factory, analyst_actor):
        survey = _make_survey_orm()
        uow = make_uow(survey=survey)
        data = request_factory()
        with pytest.raises(ForbiddenError):
            await SurveyResponseService(uow).submit(survey.id, data, analyst_actor)
        uow.commit.assert_not_called()

    async def test_field_worker_without_establishment_access_allowed(
        self, make_uow, request_factory, field_worker_actor
    ):
        """The establishment on a response is data, not permission. A field
        worker with no relation at all may still answer for it."""
        survey = _make_survey_orm(response_target=SurveyResponseTarget.ESTABLISHMENT)
        uow = make_uow(survey=survey, relation=None)
        data = request_factory(establishment_id=uuid.uuid4())
        response, created = await SurveyResponseService(uow).submit(
            survey.id, data, field_worker_actor
        )
        assert created is True
        assert isinstance(response, SurveyResponseDomain)
        uow.user_establishment_repo.get_relation.assert_not_called()
        uow.commit.assert_called_once()

    async def test_survey_not_found(self, make_uow, request_factory, admin_actor):
        uow = make_uow(survey=None)
        data = request_factory()
        with pytest.raises(SurveyNotFoundError):
            await SurveyResponseService(uow).submit(uuid.uuid4(), data, admin_actor)

    async def test_establishment_not_found(
        self, make_uow, request_factory, admin_actor
    ):
        survey = _make_survey_orm(response_target=SurveyResponseTarget.ESTABLISHMENT)
        uow = make_uow(survey=survey, establishment=None)
        data = request_factory(establishment_id=uuid.uuid4())
        with pytest.raises(EstablishmentNotFoundError):
            await SurveyResponseService(uow).submit(survey.id, data, admin_actor)

    async def test_subject_not_found(self, make_uow, request_factory, admin_actor):
        survey = _make_survey_orm(response_target=SurveyResponseTarget.SUBJECT)
        uow = make_uow(survey=survey, subject=None)
        data = request_factory(subject_id=uuid.uuid4())
        with pytest.raises(SubjectNotFoundError):
            await SurveyResponseService(uow).submit(survey.id, data, admin_actor)

    async def test_subject_not_found_takes_precedence_over_required_number(
        self, make_uow, request_factory, admin_actor
    ):
        survey = _make_survey_orm(
            response_target=SurveyResponseTarget.SUBJECT,
            requires_response_number=True,
        )
        uow = make_uow(survey=survey, subject=None)
        data = request_factory(subject_id=uuid.uuid4(), response_number=None)

        with pytest.raises(SubjectNotFoundError):
            await SurveyResponseService(uow).submit(survey.id, data, admin_actor)

    async def test_required_question_missing_rejected_no_partial_save(
        self, make_uow, request_factory, admin_actor
    ):
        question = _make_question(is_required=True)
        survey = _make_survey_orm(questions=[question])
        uow = make_uow(survey=survey)
        data = request_factory(answers={})
        with pytest.raises(InvalidSurveyResponseError):
            await SurveyResponseService(uow).submit(survey.id, data, admin_actor)
        uow.survey_response_repo.create.assert_not_called()
        uow.commit.assert_not_called()

    async def test_success_increments_response_count_and_commits(
        self, make_uow, request_factory, admin_actor
    ):
        survey = _make_survey_orm()
        uow = make_uow(survey=survey)
        data = request_factory()
        response, created = await SurveyResponseService(uow).submit(
            survey.id, data, admin_actor
        )
        assert created is True
        uow.survey_repo.increment_response_count.assert_awaited_once_with(survey.id)
        uow.commit.assert_called_once()

    async def test_replayed_id_returns_existing_for_authorized_actor(
        self, make_uow, request_factory, admin_actor
    ):
        survey_id = uuid.uuid4()
        existing = _make_response(survey_id=survey_id)
        uow = make_uow(existing_response=existing)
        data = request_factory(id=existing.id)
        response, created = await SurveyResponseService(uow).submit(
            survey_id, data, admin_actor
        )
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
            await SurveyResponseService(uow).submit(
                existing.survey_id, data, analyst_actor
            )
        uow.survey_response_repo.create.assert_not_called()

    async def test_replayed_id_under_a_different_survey_rejected(
        self, make_uow, request_factory, admin_actor
    ):
        """One id reused across two surveys would otherwise hand back the first
        survey's answers as a 200 and skip the second's uniqueness rule."""
        existing = _make_response(survey_id=uuid.uuid4())
        uow = make_uow(existing_response=existing)
        data = request_factory(id=existing.id)
        with pytest.raises(InvalidSurveyResponseError):
            await SurveyResponseService(uow).submit(uuid.uuid4(), data, admin_actor)
        uow.survey_response_repo.create.assert_not_called()
        uow.commit.assert_not_called()

    async def test_replayed_id_checked_before_survey_is_even_loaded(
        self, make_uow, request_factory, field_worker_actor
    ):
        """Id-first ordering: a retried sync must short-circuit before the
        target's uniqueness rule, or a device would be told someone else
        already answered when it was itself, seconds earlier."""
        existing = _make_response()
        uow = make_uow(existing_response=existing)
        data = request_factory(id=existing.id)
        response, created = await SurveyResponseService(uow).submit(
            existing.survey_id, data, field_worker_actor
        )
        assert created is False
        assert response.id == existing.id
        uow.survey_repo.get_by_id.assert_not_called()
        uow.survey_response_repo.get_by_target.assert_not_called()
        uow.survey_response_repo.create.assert_not_called()

    async def test_race_on_create_returns_existing(
        self, make_uow, request_factory, admin_actor
    ):
        survey = _make_survey_orm()
        response_id = uuid.uuid4()
        existing = _make_response(survey_id=survey.id)
        existing.id = response_id
        uow = make_uow(survey=survey)
        uow.survey_response_repo.get_by_id = AsyncMock(side_effect=[None, existing])
        uow.survey_response_repo.create = AsyncMock(
            side_effect=UniqueConstraintError("id", response_id)
        )
        data = request_factory(id=response_id)
        response, created = await SurveyResponseService(uow).submit(
            survey.id, data, admin_actor
        )
        assert created is False
        assert response.id == response_id
        uow.commit.assert_not_called()


class TestResolveTarget:
    """The payload must name exactly the entity the survey targets."""

    @pytest.fixture
    def request_factory(self):
        def _make(**overrides):
            data = dict(answers={}, response_number=1, event_at=NOW)
            data.update(overrides)
            return SurveyResponseRequest(**data)

        return _make

    async def test_subject_survey_requires_subject_id(
        self, make_uow, request_factory, admin_actor
    ):
        survey = _make_survey_orm(response_target=SurveyResponseTarget.SUBJECT)
        uow = make_uow(survey=survey)
        with pytest.raises(InvalidSurveyResponseError):
            await SurveyResponseService(uow).submit(
                survey.id, request_factory(), admin_actor
            )

    async def test_subject_survey_rejects_establishment_id(
        self, make_uow, request_factory, admin_actor
    ):
        survey = _make_survey_orm(response_target=SurveyResponseTarget.SUBJECT)
        uow = make_uow(survey=survey)
        data = request_factory(subject_id=uuid.uuid4(), establishment_id=uuid.uuid4())
        with pytest.raises(InvalidSurveyResponseError):
            await SurveyResponseService(uow).submit(survey.id, data, admin_actor)

    async def test_establishment_survey_requires_establishment_id(
        self, make_uow, request_factory, admin_actor
    ):
        survey = _make_survey_orm(response_target=SurveyResponseTarget.ESTABLISHMENT)
        uow = make_uow(survey=survey)
        with pytest.raises(InvalidSurveyResponseError):
            await SurveyResponseService(uow).submit(
                survey.id, request_factory(), admin_actor
            )

    async def test_establishment_survey_rejects_subject_id(
        self, make_uow, request_factory, admin_actor
    ):
        survey = _make_survey_orm(response_target=SurveyResponseTarget.ESTABLISHMENT)
        uow = make_uow(survey=survey)
        data = request_factory(subject_id=uuid.uuid4(), establishment_id=uuid.uuid4())
        with pytest.raises(InvalidSurveyResponseError):
            await SurveyResponseService(uow).submit(survey.id, data, admin_actor)

    @pytest.mark.parametrize("field", ["subject_id", "establishment_id"])
    async def test_anonymous_survey_rejects_any_entity(
        self, make_uow, request_factory, admin_actor, field
    ):
        survey = _make_survey_orm(response_target=SurveyResponseTarget.ANONYMOUS)
        uow = make_uow(survey=survey)
        data = request_factory(**{field: uuid.uuid4()})
        with pytest.raises(InvalidSurveyResponseError):
            await SurveyResponseService(uow).submit(survey.id, data, admin_actor)

    async def test_subject_survey_persists_subject_and_no_establishment(
        self, make_uow, request_factory, admin_actor
    ):
        survey = _make_survey_orm(response_target=SurveyResponseTarget.SUBJECT)
        subject_id = uuid.uuid4()
        uow = make_uow(survey=survey)
        await SurveyResponseService(uow).submit(
            survey.id, request_factory(subject_id=subject_id), admin_actor
        )
        kwargs = uow.survey_response_repo.create.call_args.kwargs
        assert kwargs["subject_id"] == subject_id
        assert kwargs["establishment_id"] is None

    async def test_anonymous_survey_persists_neither(
        self, make_uow, request_factory, admin_actor
    ):
        survey = _make_survey_orm(response_target=SurveyResponseTarget.ANONYMOUS)
        uow = make_uow(survey=survey)
        await SurveyResponseService(uow).submit(
            survey.id, request_factory(), admin_actor
        )
        kwargs = uow.survey_response_repo.create.call_args.kwargs
        assert kwargs["subject_id"] is None
        assert kwargs["establishment_id"] is None
        uow.survey_response_repo.get_by_target.assert_not_called()


class TestTargetUniqueness:
    """A subject, and an establishment, answer a given survey once. Anonymous
    surveys are unbounded."""

    @pytest.fixture
    def request_factory(self):
        def _make(**overrides):
            data = dict(answers={}, response_number=1, event_at=NOW)
            data.update(overrides)
            return SurveyResponseRequest(**data)

        return _make

    @staticmethod
    def _answered_response():
        response = _make_response(subject_id=uuid.uuid4())
        # `name` is a MagicMock constructor kwarg, so it must be assigned after.
        submitted_by = MagicMock(id=uuid.uuid4())
        submitted_by.name = "Ana"
        submitted_by.last_name = "García"
        response.submitted_by = submitted_by
        return response

    async def test_subject_already_answered_conflicts(
        self, make_uow, request_factory, admin_actor
    ):
        survey = _make_survey_orm(response_target=SurveyResponseTarget.SUBJECT)
        uow = make_uow(survey=survey, target_response=self._answered_response())
        data = request_factory(subject_id=uuid.uuid4())
        with pytest.raises(SurveyResponseAlreadyExistsError):
            await SurveyResponseService(uow).submit(survey.id, data, admin_actor)
        uow.survey_response_repo.create.assert_not_called()
        uow.commit.assert_not_called()
        # One lookup, not two: the row found by the pre-check is the same row
        # the 409 payload is built from.
        assert uow.survey_response_repo.get_by_target.await_count == 1

    async def test_establishment_already_answered_conflicts(
        self, make_uow, request_factory, admin_actor
    ):
        survey = _make_survey_orm(response_target=SurveyResponseTarget.ESTABLISHMENT)
        uow = make_uow(survey=survey, target_response=self._answered_response())
        data = request_factory(establishment_id=uuid.uuid4())
        with pytest.raises(SurveyResponseAlreadyExistsError):
            await SurveyResponseService(uow).submit(survey.id, data, admin_actor)

    async def test_target_conflict_takes_precedence_over_required_number(
        self, make_uow, request_factory, admin_actor
    ):
        survey = _make_survey_orm(
            response_target=SurveyResponseTarget.SUBJECT,
            requires_response_number=True,
        )
        uow = make_uow(survey=survey, target_response=self._answered_response())
        data = request_factory(subject_id=uuid.uuid4(), response_number=None)

        with pytest.raises(SurveyResponseAlreadyExistsError):
            await SurveyResponseService(uow).submit(survey.id, data, admin_actor)

    async def test_conflict_payload_names_who_answered_and_when(
        self, make_uow, request_factory, admin_actor
    ):
        survey = _make_survey_orm(response_target=SurveyResponseTarget.SUBJECT)
        existing = self._answered_response()
        uow = make_uow(survey=survey, target_response=existing)
        data = request_factory(subject_id=uuid.uuid4())
        with pytest.raises(SurveyResponseAlreadyExistsError) as exc_info:
            await SurveyResponseService(uow).submit(survey.id, data, admin_actor)
        payload = exc_info.value.extensions["existing_response"]
        assert payload["id"] == str(existing.id)
        assert payload["submitted_by"]["name"] == "Ana"
        # Pre-serialized to JSON primitives (Pydantic renders UTC as "Z"), since
        # the problem+json handler passes extensions straight to JSONResponse.
        assert payload["event_at"] == "2026-01-01T00:00:00Z"

    async def test_anonymous_survey_never_conflicts(
        self, make_uow, request_factory, admin_actor
    ):
        survey = _make_survey_orm(response_target=SurveyResponseTarget.ANONYMOUS)
        uow = make_uow(survey=survey, target_response=self._answered_response())
        _, created = await SurveyResponseService(uow).submit(
            survey.id, request_factory(), admin_actor
        )
        assert created is True

    async def test_duplicate_number_is_allowed_for_anonymous_responses(
        self, make_uow, request_factory, admin_actor
    ):
        survey = _make_survey_orm(response_target=SurveyResponseTarget.ANONYMOUS)
        uow = make_uow(survey=survey)

        _, created = await SurveyResponseService(uow).submit(
            survey.id, request_factory(response_number=1), admin_actor
        )

        assert created is True
        assert uow.survey_response_repo.create.call_args.kwargs["response_number"] == 1

    async def test_raced_target_collision_becomes_conflict_not_replay(
        self, make_uow, request_factory, admin_actor
    ):
        """The repository names the violated constraint. Mistaking a target
        collision for an id replay sends it down the replay path, where the
        lookup finds nothing and the error escapes as a 500."""
        survey = _make_survey_orm(response_target=SurveyResponseTarget.SUBJECT)
        existing = self._answered_response()
        uow = make_uow(survey=survey)
        uow.survey_response_repo.get_by_target = AsyncMock(side_effect=[None, existing])
        uow.survey_response_repo.create = AsyncMock(
            side_effect=UniqueConstraintError("subject_id", uuid.uuid4())
        )
        data = request_factory(id=uuid.uuid4(), subject_id=uuid.uuid4())
        with pytest.raises(SurveyResponseAlreadyExistsError):
            await SurveyResponseService(uow).submit(survey.id, data, admin_actor)
        uow.commit.assert_not_called()
