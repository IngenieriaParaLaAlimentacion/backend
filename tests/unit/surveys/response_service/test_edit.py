import uuid
from datetime import timedelta
from unittest.mock import MagicMock

import pytest

from app.domain.survey_response import (
    SurveyResponseDomain,
)
from app.domain.user import UserActor, UserRole
from app.exceptions.domain_exceptions import (
    EstablishmentAccessDeniedError,
    ForbiddenError,
    InvalidSurveyResponseError,
    SurveyResponseNotFoundError,
)
from app.services.surveys.survey_response_service import SurveyResponseService
from tests.unit.surveys.response_service.helpers import (
    NOW,
    _make_question,
    _make_response,
    _make_survey_orm,
)


class TestEdit:
    @pytest.mark.parametrize("setting", [False, None])
    async def test_optional_survey_edit_can_clear_number(
        self, make_uow, edit_factory, admin_actor, setting
    ):
        survey = _make_survey_orm(requires_response_number=setting)
        response = _make_response(survey_id=survey.id, response_number=9)
        uow = make_uow(survey=survey, existing_response=response)

        result = await SurveyResponseService(uow).edit(
            response.survey_id,
            response.id,
            edit_factory(response_number=None),
            admin_actor,
        )

        assert result.response_number is None
        assert (
            uow.survey_response_edit_repo.create.call_args.kwargs["response_number"]
            is None
        )
        assert (
            uow.survey_response_repo.update_answers.call_args.kwargs["response_number"]
            is None
        )

    async def test_required_survey_edit_rejects_missing_number_without_audit(
        self, make_uow, edit_factory, admin_actor
    ):
        survey = _make_survey_orm(requires_response_number=True)
        response = _make_response(survey_id=survey.id)
        uow = make_uow(survey=survey, existing_response=response)

        with pytest.raises(InvalidSurveyResponseError):
            await SurveyResponseService(uow).edit(
                response.survey_id,
                response.id,
                edit_factory(response_number=None),
                admin_actor,
            )

        uow.survey_response_edit_repo.create.assert_not_called()
        uow.survey_response_repo.update_answers.assert_not_called()
        uow.commit.assert_not_called()

    async def test_response_not_found(self, make_uow, edit_factory, admin_actor):
        uow = make_uow(existing_response=None)
        with pytest.raises(SurveyResponseNotFoundError):
            await SurveyResponseService(uow).edit(
                uuid.uuid4(), uuid.uuid4(), edit_factory(), admin_actor
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
                response.survey_id, response.id, edit_factory(), field_worker_actor
            )
        uow.survey_response_edit_repo.create.assert_not_called()

    async def test_owner_field_worker_allowed(self, make_uow, edit_factory):
        actor = UserActor(user_id=uuid.uuid4(), role=UserRole.FIELD_WORKER)
        response = _make_response(submitted_by_id=actor.user_id)
        survey = _make_survey_orm()
        response.survey_id = survey.id
        uow = make_uow(survey=survey, existing_response=response)
        result = await SurveyResponseService(uow).edit(
            response.survey_id, response.id, edit_factory(), actor
        )
        assert isinstance(result, SurveyResponseDomain)
        uow.commit.assert_called_once()

    async def test_owner_analyst_without_approved_access_forbidden(
        self, make_uow, edit_factory, analyst_actor
    ):
        """An analyst whose link was withdrawn cannot keep editing."""
        response = _make_response(
            submitted_by_id=analyst_actor.user_id, establishment_id=uuid.uuid4()
        )
        survey = _make_survey_orm()
        response.survey_id = survey.id
        uow = make_uow(survey=survey, existing_response=response, relation=None)
        with pytest.raises(EstablishmentAccessDeniedError):
            await SurveyResponseService(uow).edit(
                response.survey_id, response.id, edit_factory(), analyst_actor
            )
        uow.survey_response_edit_repo.create.assert_not_called()

    async def test_admin_override_allowed(self, make_uow, edit_factory, admin_actor):
        response = _make_response(submitted_by_id=uuid.uuid4())
        survey = _make_survey_orm()
        response.survey_id = survey.id
        uow = make_uow(survey=survey, existing_response=response)
        result = await SurveyResponseService(uow).edit(
            response.survey_id, response.id, edit_factory(), admin_actor
        )
        assert isinstance(result, SurveyResponseDomain)

    async def test_replayed_edit_id_returns_unchanged(
        self, make_uow, edit_factory, admin_actor
    ):
        response = _make_response()
        existing_edit = MagicMock(response_id=response.id)
        uow = make_uow(existing_response=response, existing_edit=existing_edit)
        result = await SurveyResponseService(uow).edit(
            response.survey_id, response.id, edit_factory(id=uuid.uuid4()), admin_actor
        )
        assert result.id == response.id
        uow.survey_response_edit_repo.create.assert_not_called()
        uow.commit.assert_not_called()

    async def test_edit_id_of_another_response_is_rejected(
        self, make_uow, edit_factory, admin_actor
    ):
        response = _make_response()
        existing_edit = MagicMock(response_id=uuid.uuid4())
        uow = make_uow(existing_response=response, existing_edit=existing_edit)
        with pytest.raises(InvalidSurveyResponseError):
            await SurveyResponseService(uow).edit(
                response.survey_id,
                response.id,
                edit_factory(id=uuid.uuid4()),
                admin_actor,
            )
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
            response.survey_id,
            response.id,
            edit_factory(answers={}, event_at=new_time),
            admin_actor,
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
            response.survey_id,
            response.id,
            edit_factory(answers={}, event_at=older_time),
            admin_actor,
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
                response.survey_id, response.id, edit_factory(answers={}), admin_actor
            )
        uow.survey_response_edit_repo.create.assert_not_called()

    async def test_edit_accepts_a_number_used_by_another_response(
        self, make_uow, edit_factory, admin_actor
    ):
        survey = _make_survey_orm()
        response = _make_response(survey_id=survey.id, response_number=2)
        uow = make_uow(survey=survey, existing_response=response)

        result = await SurveyResponseService(uow).edit(
            response.survey_id,
            response.id,
            edit_factory(response_number=1),
            admin_actor,
        )

        assert result.response_number == 1
        assert (
            uow.survey_response_edit_repo.create.call_args.kwargs["response_number"]
            == 1
        )
        assert (
            uow.survey_response_repo.update_answers.call_args.kwargs["response_number"]
            == 1
        )
