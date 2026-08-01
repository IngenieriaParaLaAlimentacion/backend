import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from app.domain.survey_response import SurveyResponseSummaryParams
from app.domain.user import UserActor, UserRole
from app.exceptions.domain_exceptions import ForbiddenError
from app.services.analytics_service import AnalyticsService

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.fixture
def make_uow():
    def _make(summary=(0, 0, None)):
        uow = AsyncMock()
        uow.survey_response_repo.get_survey_response_summary = AsyncMock(
            return_value=summary
        )
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


class TestGetSurveyResponseSummary:
    pytestmark = pytest.mark.asyncio

    async def test_admin_gets_summary(self, make_uow, admin_actor):
        uow = make_uow(summary=(12, 5, NOW))

        result = await AnalyticsService(uow).get_survey_response_summary(
            admin_actor, SurveyResponseSummaryParams()
        )

        assert result.response_count == 12
        assert result.participating_establishments_count == 5
        assert result.last_event_at == NOW

    async def test_analyst_can_view(self, make_uow, analyst_actor):
        uow = make_uow(summary=(3, 2, NOW))

        result = await AnalyticsService(uow).get_survey_response_summary(
            analyst_actor, SurveyResponseSummaryParams()
        )

        assert result.response_count == 3

    async def test_no_matching_responses_returns_zero_and_none(
        self, make_uow, admin_actor
    ):
        uow = make_uow(summary=(0, 0, None))

        result = await AnalyticsService(uow).get_survey_response_summary(
            admin_actor, SurveyResponseSummaryParams()
        )

        assert result.response_count == 0
        assert result.participating_establishments_count == 0
        assert result.last_event_at is None

    async def test_field_worker_forbidden(self, make_uow, field_worker_actor):
        uow = make_uow()

        with pytest.raises(ForbiddenError):
            await AnalyticsService(uow).get_survey_response_summary(
                field_worker_actor, SurveyResponseSummaryParams()
            )
        uow.survey_response_repo.get_survey_response_summary.assert_not_awaited()

    async def test_passes_params_through_to_repo(self, make_uow, admin_actor):
        uow = make_uow()
        survey_id = uuid.uuid4()
        params = SurveyResponseSummaryParams(
            survey_id=survey_id,
            event_at_from=NOW,
            city="Cordoba",
        )

        await AnalyticsService(uow).get_survey_response_summary(admin_actor, params)

        uow.survey_response_repo.get_survey_response_summary.assert_awaited_once_with(
            params
        )
