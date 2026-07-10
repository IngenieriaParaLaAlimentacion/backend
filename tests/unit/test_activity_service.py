import uuid
from datetime import datetime, timezone
from math import ceil
from unittest.mock import AsyncMock

import pytest

from app.domain.activity import ActivityItemDomain, ActivityListingParams, ActivityType
from app.domain.pagination import PaginatedResult
from app.domain.subject import Sex, SubjectBase
from app.domain.user import UserActor, UserRole
from app.services.activity_service import ActivityService


@pytest.fixture
def make_uow():
    def _make(items=None, total=0):
        uow = AsyncMock()
        uow.activity_repo.get_activity_feed = AsyncMock(
            return_value=(items or [], total)
        )
        return uow

    return _make


@pytest.fixture
def subject_item():
    return ActivityItemDomain(
        type=ActivityType.SUBJECT,
        occurred_at=datetime(2024, 6, 1, tzinfo=timezone.utc),
        subject=SubjectBase(
            id=uuid.uuid4(), dni=12345678, sex=Sex.MALE, name="Ana", last_name="Perez"
        ),
    )


class TestActorIdCoercion:
    pytestmark = pytest.mark.asyncio

    async def test_coerces_str_actor_id_to_uuid(self, make_uow):
        """The real dependency chain produces a str user_id (JWT 'sub' claim);
        the repo call must always receive a UUID."""
        uow = make_uow()
        user_id = uuid.uuid4()
        actor = UserActor(user_id=str(user_id), role=UserRole.FIELD_WORKER)

        await ActivityService(uow).get_recent_activity(
            actor, page=1, page_size=20, params=ActivityListingParams()
        )

        call_kwargs = uow.activity_repo.get_activity_feed.call_args.kwargs
        assert isinstance(call_kwargs["actor_id"], uuid.UUID)
        assert call_kwargs["actor_id"] == user_id


class TestPaginationMath:
    pytestmark = pytest.mark.asyncio

    async def test_passes_correct_offset(self, make_uow):
        uow = make_uow()
        actor = UserActor(user_id=str(uuid.uuid4()), role=UserRole.FIELD_WORKER)

        await ActivityService(uow).get_recent_activity(
            actor, page=3, page_size=10, params=ActivityListingParams()
        )

        call_kwargs = uow.activity_repo.get_activity_feed.call_args.kwargs
        assert call_kwargs["limit"] == 10
        assert call_kwargs["offset"] == 20

    async def test_page_below_one_is_clamped_to_one(self, make_uow):
        uow = make_uow()
        actor = UserActor(user_id=str(uuid.uuid4()), role=UserRole.FIELD_WORKER)

        result = await ActivityService(uow).get_recent_activity(
            actor, page=0, page_size=20, params=ActivityListingParams()
        )

        call_kwargs = uow.activity_repo.get_activity_feed.call_args.kwargs
        assert call_kwargs["offset"] == 0
        assert result.page == 1

    async def test_calculates_total_pages(self, make_uow, subject_item):
        uow = make_uow(items=[subject_item], total=23)
        actor = UserActor(user_id=str(uuid.uuid4()), role=UserRole.FIELD_WORKER)

        result = await ActivityService(uow).get_recent_activity(
            actor, page=1, page_size=5, params=ActivityListingParams()
        )

        assert isinstance(result, PaginatedResult)
        assert result.total_pages == ceil(23 / 5)


class TestActivityTypeFilter:
    pytestmark = pytest.mark.asyncio

    @pytest.mark.parametrize(
        "activity_type",
        [
            None,
            ActivityType.SUBJECT,
            ActivityType.MEASUREMENT,
            ActivityType.SURVEY_RESPONSE,
        ],
    )
    async def test_passes_activity_type_through_unchanged(
        self, make_uow, activity_type
    ):
        uow = make_uow()
        actor = UserActor(user_id=str(uuid.uuid4()), role=UserRole.FIELD_WORKER)

        await ActivityService(uow).get_recent_activity(
            actor,
            page=1,
            page_size=20,
            params=ActivityListingParams(activity_type=activity_type),
        )

        call_kwargs = uow.activity_repo.get_activity_feed.call_args.kwargs
        assert call_kwargs["activity_type"] == activity_type


class TestGetRecentActivityReturnValue:
    pytestmark = pytest.mark.asyncio

    async def test_returns_items_from_repo_unchanged(self, make_uow, subject_item):
        uow = make_uow(items=[subject_item], total=1)
        actor = UserActor(user_id=str(uuid.uuid4()), role=UserRole.FIELD_WORKER)

        result = await ActivityService(uow).get_recent_activity(
            actor, page=1, page_size=20, params=ActivityListingParams()
        )

        assert result.items == [subject_item]
        assert result.total == 1
