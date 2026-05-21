import uuid
from math import ceil
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.user import UserRole, UserStatus
from app.exceptions.domain_exceptions import (
    UserEstablishmentNotFoundError,
    UserNotFoundError,
)
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


def _make_relation(establishment_id):
    rel = MagicMock()
    rel.establishment_id = establishment_id
    return rel


def _make_approve_uow(user=None, relations=None, establishments=None):
    uow = AsyncMock()
    uow.user_repo.get_by_id = AsyncMock(return_value=user)
    uow.user_establishment_repo.get_by_user_id = AsyncMock(return_value=relations or [])
    uow.establishment_repo.find_by_ids = AsyncMock(return_value=establishments or [])
    uow.user_repo.update_status = AsyncMock()
    uow.user_establishment_repo.update_statuses = AsyncMock()
    uow.commit = AsyncMock()
    return uow


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


class TestApproveManager:
    @pytest.mark.asyncio
    async def test_partial_approval_annotates_statuses_correctly(
        self, make_establishment
    ):
        user = _make_user(
            role=UserRole.ESTABLISHMENT_MANAGER, status=UserStatus.PENDING_VALIDATION
        )
        estab1 = make_establishment(name="Hospital")
        estab2 = make_establishment(name="Clínica")
        uow = _make_approve_uow(
            user=user,
            relations=[_make_relation(estab1.id), _make_relation(estab2.id)],
            establishments=[estab1, estab2],
        )
        service = AdminService(uow)

        result = await service.approve_manager(user.id, [estab1.id])

        approved = [e for e in result.establishments if e.status == "approved"]
        rejected = [e for e in result.establishments if e.status == "rejected"]
        assert len(approved) == 1 and approved[0].id == estab1.id
        assert len(rejected) == 1 and rejected[0].id == estab2.id

    @pytest.mark.asyncio
    async def test_all_approved(self, make_establishment):
        user = _make_user(role=UserRole.ESTABLISHMENT_MANAGER)
        estab1 = make_establishment()
        estab2 = make_establishment()
        uow = _make_approve_uow(
            user=user,
            relations=[_make_relation(estab1.id), _make_relation(estab2.id)],
            establishments=[estab1, estab2],
        )
        service = AdminService(uow)

        result = await service.approve_manager(user.id, [estab1.id, estab2.id])

        assert all(e.status == "approved" for e in result.establishments)

    @pytest.mark.asyncio
    async def test_sets_user_status_to_active(self, make_establishment):
        user = _make_user(
            role=UserRole.ESTABLISHMENT_MANAGER, status=UserStatus.PENDING_VALIDATION
        )
        estab = make_establishment()
        uow = _make_approve_uow(
            user=user,
            relations=[_make_relation(estab.id)],
            establishments=[estab],
        )
        service = AdminService(uow)

        await service.approve_manager(user.id, [estab.id])

        uow.user_repo.update_status.assert_called_once_with(user.id, UserStatus.ACTIVE)
        uow.user_establishment_repo.update_statuses.assert_called_once_with(
            user.id, [estab.id]
        )
        uow.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_user_not_found_raises_error(self):
        uow = _make_approve_uow(user=None)
        service = AdminService(uow)

        with pytest.raises(UserNotFoundError):
            await service.approve_manager(uuid.uuid4(), [uuid.uuid4()])

    @pytest.mark.asyncio
    async def test_invalid_establishment_id_raises_error(self, make_establishment):
        user = _make_user(role=UserRole.ESTABLISHMENT_MANAGER)
        estab = make_establishment()
        uow = _make_approve_uow(user=user, relations=[_make_relation(estab.id)])
        service = AdminService(uow)

        with pytest.raises(UserEstablishmentNotFoundError):
            await service.approve_manager(user.id, [uuid.uuid4()])

    @pytest.mark.asyncio
    async def test_idempotent_when_already_active(self, make_establishment):
        user = _make_user(role=UserRole.ESTABLISHMENT_MANAGER, status=UserStatus.ACTIVE)
        estab = make_establishment()
        uow = _make_approve_uow(
            user=user,
            relations=[_make_relation(estab.id)],
            establishments=[estab],
        )
        service = AdminService(uow)

        result = await service.approve_manager(user.id, [estab.id])

        assert result.id == user.id
        uow.commit.assert_called_once()
