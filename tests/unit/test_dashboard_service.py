import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from app.domain.survey_response import DashboardIndicatorsParams
from app.domain.user import UserActor, UserRole
from app.exceptions.domain_exceptions import ForbiddenError
from app.services.dashboard_service import DashboardService

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.fixture
def make_uow():
    def _make(indicators=(0, 0, None)):
        uow = AsyncMock()
        uow.survey_response_repo.get_dashboard_indicators = AsyncMock(
            return_value=indicators
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


class TestGetIndicators:
    pytestmark = pytest.mark.asyncio

    async def test_admin_gets_indicators(self, make_uow, admin_actor):
        uow = make_uow(indicators=(12, 5, NOW))

        result = await DashboardService(uow).get_indicators(
            admin_actor, DashboardIndicatorsParams()
        )

        assert result.response_count == 12
        assert result.participating_establishments_count == 5
        assert result.last_event_at == NOW

    async def test_analyst_can_view(self, make_uow, analyst_actor):
        uow = make_uow(indicators=(3, 2, NOW))

        result = await DashboardService(uow).get_indicators(
            analyst_actor, DashboardIndicatorsParams()
        )

        assert result.response_count == 3

    async def test_no_matching_responses_returns_zero_and_none(
        self, make_uow, admin_actor
    ):
        uow = make_uow(indicators=(0, 0, None))

        result = await DashboardService(uow).get_indicators(
            admin_actor, DashboardIndicatorsParams()
        )

        assert result.response_count == 0
        assert result.participating_establishments_count == 0
        assert result.last_event_at is None

    async def test_field_worker_forbidden(self, make_uow, field_worker_actor):
        uow = make_uow()

        with pytest.raises(ForbiddenError):
            await DashboardService(uow).get_indicators(
                field_worker_actor, DashboardIndicatorsParams()
            )
        uow.survey_response_repo.get_dashboard_indicators.assert_not_awaited()

    async def test_passes_params_through_to_repo(self, make_uow, admin_actor):
        uow = make_uow()
        survey_id = uuid.uuid4()
        params = DashboardIndicatorsParams(
            survey_id=survey_id,
            event_at_from=NOW,
            city="Cordoba",
        )

        await DashboardService(uow).get_indicators(admin_actor, params)

        uow.survey_response_repo.get_dashboard_indicators.assert_awaited_once_with(
            params
        )
