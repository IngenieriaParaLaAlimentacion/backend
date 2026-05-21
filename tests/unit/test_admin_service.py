import uuid
from math import ceil
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.user import UserRole, UserStatus
from app.services.admin_service import AdminService


def _make_user(
    *,
    name="Test",
    last_name="User",
    email=None,
    role=UserRole.PROFESSIONAL,
    status=UserStatus.ACTIVE,
):
    user = MagicMock()
    user.id = uuid.uuid4()
    user.name = name
    user.last_name = last_name
    user.email = email or f"user_{uuid.uuid4().hex[:6]}@example.com"
    user.role = role
    user.status = status
    return user


@pytest.fixture
def make_uow():
    def _make(users=None, total=0, establishment_ids_by_user=None, establishments=None):
        uow = AsyncMock()
        users = users or []
        uow.user_repo.get_paginated = AsyncMock(return_value=(users, total))
        uow.user_establishment_repo.get_by_user_ids = AsyncMock(
            return_value=establishment_ids_by_user
            if establishment_ids_by_user is not None
            else {user.id: [] for user in users}
        )
        uow.establishment_repo.find_by_ids = AsyncMock(
            return_value=establishments or []
        )
        return uow

    return _make


class TestGetPaginatedUsers:
    @pytest.mark.asyncio
    async def test_returns_correct_pagination_metadata(self, make_uow):
        users = [_make_user() for _ in range(3)]
        service = AdminService(make_uow(users=users, total=3))

        result = await service.get_users_paginated(page=1, page_size=20)

        assert len(result.items) == 3
        assert result.items[0].id == users[0].id
        assert result.total == 3
        assert result.page == 1
        assert result.page_size == 20
        assert result.total_pages == 1

    @pytest.mark.asyncio
    async def test_calculates_offset_correctly(self, make_uow):
        uow = make_uow()
        service = AdminService(uow)

        await service.get_users_paginated(page=3, page_size=20)

        uow.user_repo.get_paginated.assert_called_once_with(
            role=None, status=None, limit=20, offset=40
        )

    @pytest.mark.asyncio
    async def test_total_pages_rounds_up(self, make_uow):
        users = [_make_user() for _ in range(5)]
        service = AdminService(make_uow(users=users, total=45))

        result = await service.get_users_paginated(page=1, page_size=20)

        assert result.total_pages == ceil(45 / 20)

    @pytest.mark.asyncio
    async def test_empty_db_returns_empty_result(self, make_uow):
        service = AdminService(make_uow())

        result = await service.get_users_paginated(page=1, page_size=20)

        assert result.items == []
        assert result.total == 0
        assert result.total_pages == 0

    @pytest.mark.asyncio
    async def test_last_page_has_fewer_items(self, make_uow):
        users = [_make_user() for _ in range(5)]
        service = AdminService(make_uow(users=users, total=45))

        result = await service.get_users_paginated(page=3, page_size=20)

        assert len(result.items) == 5
        assert result.total == 45
        assert result.total_pages == 3

    @pytest.mark.asyncio
    async def test_page_size_one(self, make_uow):
        users = [_make_user()]
        uow = make_uow(users=users, total=10)
        service = AdminService(uow)

        result = await service.get_users_paginated(page=1, page_size=1)

        assert result.total_pages == 10
        uow.user_repo.get_paginated.assert_called_once_with(
            role=None, status=None, limit=1, offset=0
        )

    @pytest.mark.asyncio
    async def test_forwards_role_filter_to_repo(self, make_uow):
        uow = make_uow()
        service = AdminService(uow)

        await service.get_users_paginated(
            page=1, page_size=20, role=UserRole.PROFESSIONAL
        )

        uow.user_repo.get_paginated.assert_called_once_with(
            role=UserRole.PROFESSIONAL, status=None, limit=20, offset=0
        )

    @pytest.mark.asyncio
    async def test_forwards_status_filter_to_repo(self, make_uow):
        uow = make_uow()
        service = AdminService(uow)

        await service.get_users_paginated(
            page=1, page_size=20, status=UserStatus.ACTIVE
        )

        uow.user_repo.get_paginated.assert_called_once_with(
            role=None, status=UserStatus.ACTIVE, limit=20, offset=0
        )

    @pytest.mark.asyncio
    async def test_skips_establishment_query_when_no_users(self, make_uow):
        uow = make_uow()
        service = AdminService(uow)

        await service.get_users_paginated(page=1, page_size=20)

        uow.user_establishment_repo.get_by_user_ids.assert_not_called()

    @pytest.mark.asyncio
    async def test_users_without_establishments_get_empty_list(self, make_uow):
        user = _make_user()
        service = AdminService(make_uow(users=[user], total=1))

        result = await service.get_users_paginated(page=1, page_size=20)

        assert result.items[0].establishments == []

    @pytest.mark.asyncio
    async def test_users_with_establishments_get_them_hydrated(
        self, make_uow, make_establishment
    ):
        user = _make_user()
        establishment = make_establishment(
            name="Gym Centro", address="Av. Corrientes 123"
        )

        uow = make_uow(
            users=[user],
            total=1,
            establishment_ids_by_user={user.id: [establishment.id]},
            establishments=[establishment],
        )
        service = AdminService(uow)

        result = await service.get_users_paginated(page=1, page_size=20)

        assert len(result.items[0].establishments) == 1
        assert result.items[0].establishments[0].id == establishment.id
        assert result.items[0].establishments[0].name == "Gym Centro"
