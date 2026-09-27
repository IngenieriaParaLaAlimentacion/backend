import uuid
from unittest.mock import AsyncMock

import pytest

from app.domain.survey import (
    SurveyResponseTarget,
)
from app.domain.survey_response import (
    SurveyResponseDomain,
    SurveyResponseListingParams,
    SurveyResponseSortOrder,
)
from app.domain.user import UserActor, UserRole
from app.exceptions.domain_exceptions import (
    ForbiddenError,
    InvalidListingFilterError,
    SurveyNotFoundError,
    SurveyResponseNotFoundError,
)
from app.services.surveys.survey_response_service import SurveyResponseService
from tests.unit.surveys.response_service.helpers import (
    NOW,
    _make_response,
    _make_survey_orm,
)


class TestGet:
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


class TestListBySurvey:
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
    async def test_passes_params_through_to_repo(self, make_uow, admin_actor):
        survey = _make_survey_orm(response_target=SurveyResponseTarget.ESTABLISHMENT)
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

    @pytest.mark.parametrize(
        "target",
        [SurveyResponseTarget.SUBJECT, SurveyResponseTarget.ANONYMOUS],
    )
    @pytest.mark.parametrize("field", ["city", "province"])
    async def test_location_filter_rejected_without_establishments(
        self, make_uow, admin_actor, target, field
    ):
        """Those responses carry no establishment, so the join would silently
        drop them — an empty page reads as "no data", not "wrong filter"."""
        survey = _make_survey_orm(response_target=target)
        uow = make_uow(survey=survey)
        uow.survey_response_repo.list_by_survey = AsyncMock(return_value=([], 0))
        params = SurveyResponseListingParams(**{field: "Cordoba"})

        with pytest.raises(InvalidListingFilterError):
            await SurveyResponseService(uow).list_by_survey(
                survey.id, admin_actor, page=1, page_size=20, params=params
            )
        uow.survey_response_repo.list_by_survey.assert_not_called()

    @pytest.mark.parametrize(
        "target",
        [SurveyResponseTarget.SUBJECT, SurveyResponseTarget.ANONYMOUS],
    )
    async def test_establishment_filter_rejected_without_establishments(
        self, make_uow, admin_actor, target
    ):
        """Same reasoning as city/province: the column it filters on is null
        for every response to this survey."""
        survey = _make_survey_orm(response_target=target)
        uow = make_uow(survey=survey)
        uow.survey_response_repo.list_by_survey = AsyncMock(return_value=([], 0))
        params = SurveyResponseListingParams(establishment_id=uuid.uuid4())

        with pytest.raises(InvalidListingFilterError):
            await SurveyResponseService(uow).list_by_survey(
                survey.id, admin_actor, page=1, page_size=20, params=params
            )
        uow.survey_response_repo.list_by_survey.assert_not_called()

    @pytest.mark.parametrize(
        "target",
        [SurveyResponseTarget.ESTABLISHMENT, SurveyResponseTarget.ANONYMOUS],
    )
    async def test_subject_filter_rejected_without_subjects(
        self, make_uow, admin_actor, target
    ):
        """Mirror of the establishment case: ``subject_id`` is null on every
        response to a survey not targeted at subjects."""
        survey = _make_survey_orm(response_target=target)
        uow = make_uow(survey=survey)
        uow.survey_response_repo.list_by_survey = AsyncMock(return_value=([], 0))
        params = SurveyResponseListingParams(subject_id=uuid.uuid4())

        with pytest.raises(InvalidListingFilterError):
            await SurveyResponseService(uow).list_by_survey(
                survey.id, admin_actor, page=1, page_size=20, params=params
            )
        uow.survey_response_repo.list_by_survey.assert_not_called()

    async def test_subject_filter_allowed_for_subject_survey(
        self, make_uow, admin_actor
    ):
        survey = _make_survey_orm(response_target=SurveyResponseTarget.SUBJECT)
        uow = make_uow(survey=survey)
        uow.survey_response_repo.list_by_survey = AsyncMock(return_value=([], 0))

        await SurveyResponseService(uow).list_by_survey(
            survey.id,
            admin_actor,
            page=1,
            page_size=20,
            params=SurveyResponseListingParams(subject_id=uuid.uuid4()),
        )
        uow.survey_response_repo.list_by_survey.assert_awaited_once()

    async def test_location_filter_allowed_for_establishment_survey(
        self, make_uow, admin_actor
    ):
        survey = _make_survey_orm(response_target=SurveyResponseTarget.ESTABLISHMENT)
        uow = make_uow(survey=survey)
        uow.survey_response_repo.list_by_survey = AsyncMock(return_value=([], 0))

        await SurveyResponseService(uow).list_by_survey(
            survey.id,
            admin_actor,
            page=1,
            page_size=20,
            params=SurveyResponseListingParams(province="Cordoba"),
        )
        uow.survey_response_repo.list_by_survey.assert_awaited_once()

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
        assert call.kwargs["params"].subject_id is None
        assert call.kwargs["params"].city is None
        assert call.kwargs["params"].sort_order == SurveyResponseSortOrder.EVENT_AT_DESC
