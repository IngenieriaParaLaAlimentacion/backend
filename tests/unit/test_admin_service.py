import uuid
from math import ceil
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domain.establishment import UserEstablishmentStatus
from app.domain.user import UserRole, UserStatus
from app.exceptions.domain_exceptions import (
    BadRequestError,
    UserEstablishmentNotFoundError,
    UserNotFoundError,
)
from app.services.admin_service import AdminService


def _make_user(
    *,
    name="Test",
    last_name="User",
    email=None,
    role=UserRole.ANALYST,
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
def mock_auth_service():
    auth = AsyncMock()
    auth.create_recovery_token = AsyncMock(return_value=(MagicMock(), "plain-token"))
    return auth


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


@pytest.fixture
def make_service(mock_auth_service):
    def _make(uow):
        return AdminService(uow, mock_auth_service)

    return _make


def _make_relation(establishment_id, status=UserEstablishmentStatus.PENDING):
    rel = MagicMock()
    rel.establishment_id = establishment_id
    rel.status = status
    return rel


def _make_approve_uow(user=None, relations=None, establishments=None):
    uow = AsyncMock()
    uow.user_repo.get_by_id = AsyncMock(return_value=user)
    uow.user_establishment_repo.get_by_user_id = AsyncMock(return_value=relations or [])
    uow.user_repo.update_status = AsyncMock()
    uow.user_establishment_repo.update_status_for_ids = AsyncMock()
    uow.establishment_repo.find_by_ids = AsyncMock(return_value=establishments or [])
    uow.commit = AsyncMock()
    return uow


def _make_user_info_uow(user=None, establishment_ids_by_user=None, establishments=None):
    uow = AsyncMock()
    uow.user_repo.get_by_id = AsyncMock(return_value=user)
    uow.user_establishment_repo.get_by_user_ids = AsyncMock(
        return_value=establishment_ids_by_user
        if establishment_ids_by_user is not None
        else ({user.id: []} if user else {})
    )
    uow.establishment_repo.find_by_ids = AsyncMock(return_value=establishments or [])
    return uow


class TestGetPaginatedUsers:
    @pytest.mark.asyncio
    async def test_returns_correct_pagination_metadata(self, make_uow, make_service):
        users = [_make_user() for _ in range(3)]
        service = make_service(make_uow(users=users, total=3))

        result = await service.get_users_paginated(page=1, page_size=20)

        assert len(result.items) == 3
        assert result.items[0].id == users[0].id
        assert result.total == 3
        assert result.page == 1
        assert result.page_size == 20
        assert result.total_pages == 1

    @pytest.mark.asyncio
    async def test_calculates_offset_correctly(self, make_uow, make_service):
        uow = make_uow()
        service = make_service(uow)

        await service.get_users_paginated(page=3, page_size=20)

        uow.user_repo.get_paginated.assert_called_once_with(
            role=None, status=None, limit=20, offset=40, search=None
        )

    @pytest.mark.asyncio
    async def test_total_pages_rounds_up(self, make_uow, make_service):
        users = [_make_user() for _ in range(5)]
        service = make_service(make_uow(users=users, total=45))

        result = await service.get_users_paginated(page=1, page_size=20)

        assert result.total_pages == ceil(45 / 20)

    @pytest.mark.asyncio
    async def test_empty_db_returns_empty_result(self, make_uow, make_service):
        service = make_service(make_uow())

        result = await service.get_users_paginated(page=1, page_size=20)

        assert result.items == []
        assert result.total == 0
        assert result.total_pages == 0

    @pytest.mark.asyncio
    async def test_last_page_has_fewer_items(self, make_uow, make_service):
        users = [_make_user() for _ in range(5)]
        service = make_service(make_uow(users=users, total=45))

        result = await service.get_users_paginated(page=3, page_size=20)

        assert len(result.items) == 5
        assert result.total == 45
        assert result.total_pages == 3

    @pytest.mark.asyncio
    async def test_page_size_one(self, make_uow, make_service):
        users = [_make_user()]
        uow = make_uow(users=users, total=10)
        service = make_service(uow)

        result = await service.get_users_paginated(page=1, page_size=1)

        assert result.total_pages == 10
        uow.user_repo.get_paginated.assert_called_once_with(
            role=None, status=None, limit=1, offset=0, search=None
        )

    @pytest.mark.asyncio
    async def test_forwards_role_filter_to_repo(self, make_uow, make_service):
        uow = make_uow()
        service = make_service(uow)

        await service.get_users_paginated(page=1, page_size=20, role=UserRole.ANALYST)

        uow.user_repo.get_paginated.assert_called_once_with(
            role=UserRole.ANALYST, status=None, limit=20, offset=0, search=None
        )

    @pytest.mark.asyncio
    async def test_forwards_status_filter_to_repo(self, make_uow, make_service):
        uow = make_uow()
        service = make_service(uow)

        await service.get_users_paginated(
            page=1, page_size=20, status=UserStatus.ACTIVE
        )

        uow.user_repo.get_paginated.assert_called_once_with(
            role=None, status=UserStatus.ACTIVE, limit=20, offset=0, search=None
        )

    @pytest.mark.asyncio
    async def test_skips_establishment_query_when_no_users(
        self, make_uow, make_service
    ):
        uow = make_uow()
        service = make_service(uow)

        await service.get_users_paginated(page=1, page_size=20)

        uow.user_establishment_repo.get_by_user_ids.assert_not_called()

    @pytest.mark.asyncio
    async def test_users_without_establishments_get_empty_list(
        self, make_uow, make_service
    ):
        user = _make_user()
        service = make_service(make_uow(users=[user], total=1))

        result = await service.get_users_paginated(page=1, page_size=20)

        assert result.items[0].establishments == []

    @pytest.mark.asyncio
    async def test_users_with_establishments_get_them_hydrated(
        self, make_uow, make_service, make_establishment
    ):
        user = _make_user()
        establishment = make_establishment(
            name="Gym Centro", formatted_address="Av. Corrientes 123"
        )

        uow = make_uow(
            users=[user],
            total=1,
            establishment_ids_by_user={user.id: [establishment.id]},
            establishments=[establishment],
        )
        service = make_service(uow)

        result = await service.get_users_paginated(page=1, page_size=20)

        assert len(result.items[0].establishments) == 1
        assert result.items[0].establishments[0].id == establishment.id
        assert result.items[0].establishments[0].name == "Gym Centro"

    @pytest.mark.asyncio
    async def test_forwards_search_to_repo(self, make_uow, make_service):
        uow = make_uow()
        service = make_service(uow)

        await service.get_users_paginated(
            page=1, page_size=20, status=UserStatus.ACTIVE, search="Name search"
        )

        uow.user_repo.get_paginated.assert_called_once_with(
            role=None,
            status=UserStatus.ACTIVE,
            limit=20,
            offset=0,
            search="Name search",
        )

    @pytest.mark.asyncio
    async def test_strips_whitespace_from_search(self, make_uow, make_service):
        uow = make_uow()
        service = make_service(uow)

        await service.get_users_paginated(page=1, page_size=20, search="  john  ")

        uow.user_repo.get_paginated.assert_called_once_with(
            role=None, status=None, limit=20, offset=0, search="john"
        )

    @pytest.mark.asyncio
    async def test_whitespace_only_search_passes_none(self, make_uow, make_service):
        uow = make_uow()
        service = make_service(uow)

        await service.get_users_paginated(page=1, page_size=20, search="   ")

        uow.user_repo.get_paginated.assert_called_once_with(
            role=None, status=None, limit=20, offset=0, search=None
        )


class TestApproveEstablishments:
    @pytest.mark.asyncio
    async def test_approves_relations_without_touching_user_status(
        self, make_establishment, mock_auth_service
    ):
        """Granting establishment access must not change the account status."""
        user = _make_user(role=UserRole.FIELD_WORKER, status=UserStatus.ACTIVE)
        estab = make_establishment()
        uow = _make_approve_uow(user=user, relations=[_make_relation(estab.id)])
        service = AdminService(uow, mock_auth_service)

        await service.approve_establishments(user.id, [estab.id])

        uow.user_repo.update_status.assert_not_called()
        uow.user_establishment_repo.update_status_for_ids.assert_called_once_with(
            user.id, [estab.id], UserEstablishmentStatus.APPROVED
        )
        uow.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_pending_user_raises_error(
        self, make_establishment, mock_auth_service
    ):
        """Establishment access can only be granted once the account is active."""
        user = _make_user(
            role=UserRole.FIELD_WORKER, status=UserStatus.PENDING_VALIDATION
        )
        estab = make_establishment()
        uow = _make_approve_uow(user=user, relations=[_make_relation(estab.id)])
        service = AdminService(uow, mock_auth_service)

        with pytest.raises(BadRequestError):
            await service.approve_establishments(user.id, [estab.id])

        uow.user_establishment_repo.update_status_for_ids.assert_not_called()
        uow.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_user_not_found_raises_error(self, mock_auth_service):
        uow = _make_approve_uow(user=None)
        service = AdminService(uow, mock_auth_service)

        with pytest.raises(UserNotFoundError):
            await service.approve_establishments(uuid.uuid4(), [uuid.uuid4()])

    @pytest.mark.asyncio
    async def test_invalid_establishment_id_raises_error(
        self, make_establishment, mock_auth_service
    ):
        user = _make_user(role=UserRole.FIELD_WORKER)
        estab = make_establishment()
        uow = _make_approve_uow(user=user, relations=[_make_relation(estab.id)])
        service = AdminService(uow, mock_auth_service)

        with pytest.raises(UserEstablishmentNotFoundError):
            await service.approve_establishments(user.id, [uuid.uuid4()])

    @pytest.mark.asyncio
    async def test_sends_access_granted_email(
        self, make_establishment, mock_auth_service
    ):
        user = _make_user(
            role=UserRole.FIELD_WORKER,
            status=UserStatus.ACTIVE,
            email="worker@test.com",
        )
        estab1 = make_establishment(name="Centro A")
        estab2 = make_establishment(name="Centro B")
        uow = _make_approve_uow(
            user=user,
            relations=[_make_relation(estab1.id), _make_relation(estab2.id)],
            establishments=[estab1, estab2],
        )
        service = AdminService(uow, mock_auth_service)

        with patch(
            "app.services.admin_service.send_access_granted_email",
            new_callable=AsyncMock,
        ) as mock_email:
            await service.approve_establishments(user.id, [estab1.id, estab2.id])

        mock_email.assert_awaited_once_with(user.email, ["Centro A", "Centro B"])

    @pytest.mark.asyncio
    async def test_email_sent_after_commit(self, make_establishment, mock_auth_service):
        user = _make_user(role=UserRole.FIELD_WORKER, status=UserStatus.ACTIVE)
        estab = make_establishment()
        uow = _make_approve_uow(
            user=user,
            relations=[_make_relation(estab.id)],
            establishments=[estab],
        )
        service = AdminService(uow, mock_auth_service)

        with patch(
            "app.services.admin_service.send_access_granted_email",
            new_callable=AsyncMock,
        ) as mock_email:
            await service.approve_establishments(user.id, [estab.id])

        uow.commit.assert_called_once()
        mock_email.assert_awaited_once()


class TestRejectEstablishments:
    @pytest.mark.asyncio
    async def test_does_not_change_user_status(
        self, make_establishment, mock_auth_service
    ):
        user = _make_user(
            role=UserRole.FIELD_WORKER, status=UserStatus.PENDING_VALIDATION
        )
        estab = make_establishment()
        uow = _make_approve_uow(user=user, relations=[_make_relation(estab.id)])
        service = AdminService(uow, mock_auth_service)

        await service.reject_establishments(user.id, [estab.id])

        uow.user_repo.update_status.assert_not_called()
        uow.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_calls_repo_with_correct_args(
        self, make_establishment, mock_auth_service
    ):
        user = _make_user(role=UserRole.FIELD_WORKER)
        estab = make_establishment()
        uow = _make_approve_uow(user=user, relations=[_make_relation(estab.id)])
        service = AdminService(uow, mock_auth_service)

        await service.reject_establishments(user.id, [estab.id])

        uow.user_establishment_repo.update_status_for_ids.assert_called_once_with(
            user.id, [estab.id], UserEstablishmentStatus.REJECTED
        )

    @pytest.mark.asyncio
    async def test_user_not_found_raises_error(self, mock_auth_service):
        uow = _make_approve_uow(user=None)
        service = AdminService(uow, mock_auth_service)

        with pytest.raises(UserNotFoundError):
            await service.reject_establishments(uuid.uuid4(), [uuid.uuid4()])

    @pytest.mark.asyncio
    async def test_invalid_establishment_id_raises_error(
        self, make_establishment, mock_auth_service
    ):
        user = _make_user(role=UserRole.FIELD_WORKER)
        estab = make_establishment()
        uow = _make_approve_uow(user=user, relations=[_make_relation(estab.id)])
        service = AdminService(uow, mock_auth_service)

        with pytest.raises(UserEstablishmentNotFoundError):
            await service.reject_establishments(user.id, [uuid.uuid4()])


class TestGetUserInfo:
    @pytest.mark.asyncio
    async def test_user_not_found_raises_error(self, mock_auth_service):
        uow = _make_user_info_uow(user=None)
        service = AdminService(uow, mock_auth_service)

        with pytest.raises(UserNotFoundError):
            await service.get_user_info(uuid.uuid4())

    @pytest.mark.asyncio
    async def test_calls_repo_with_correct_user_id(self, mock_auth_service):
        user = _make_user()
        uow = _make_user_info_uow(user=user)
        service = AdminService(uow, mock_auth_service)

        await service.get_user_info(user.id)

        uow.user_repo.get_by_id.assert_called_once_with(user.id)

    @pytest.mark.asyncio
    async def test_returns_user_with_no_establishments(self, mock_auth_service):
        user = _make_user()
        uow = _make_user_info_uow(user=user)
        service = AdminService(uow, mock_auth_service)

        result = await service.get_user_info(user.id)

        assert result.id == user.id
        assert result.establishments == []

    @pytest.mark.asyncio
    async def test_returns_user_with_hydrated_establishments(
        self, mock_auth_service, make_establishment
    ):
        user = _make_user()
        estab = make_establishment(name="Comedor Norte")
        uow = _make_user_info_uow(
            user=user,
            establishment_ids_by_user={user.id: [estab.id]},
            establishments=[estab],
        )
        service = AdminService(uow, mock_auth_service)

        result = await service.get_user_info(user.id)

        assert len(result.establishments) == 1
        assert result.establishments[0].id == estab.id
        assert result.establishments[0].name == "Comedor Norte"


class TestApproveFieldWorker:
    @pytest.mark.asyncio
    async def test_user_not_found_raises_error(self, mock_auth_service):
        uow = _make_approve_uow(user=None)
        service = AdminService(uow, mock_auth_service)

        with pytest.raises(UserNotFoundError):
            await service.approve_field_worker(uuid.uuid4(), [])

    @pytest.mark.asyncio
    async def test_approves_only_the_selected_establishments(
        self, make_establishment, mock_auth_service
    ):
        """The admin picks a subset; unselected requests stay pending."""
        user = _make_user(
            role=UserRole.FIELD_WORKER, status=UserStatus.PENDING_VALIDATION
        )
        estab1 = make_establishment()
        estab2 = make_establishment()
        uow = _make_approve_uow(
            user=user,
            relations=[_make_relation(estab1.id), _make_relation(estab2.id)],
            establishments=[estab1],
        )
        service = AdminService(uow, mock_auth_service)

        with patch(
            "app.services.admin_service.send_access_granted_email",
            new_callable=AsyncMock,
        ):
            await service.approve_field_worker(user.id, [estab1.id])

        uow.user_repo.update_status.assert_called_once_with(user.id, UserStatus.ACTIVE)
        uow.user_establishment_repo.update_status_for_ids.assert_called_once_with(
            user.id, [estab1.id], UserEstablishmentStatus.APPROVED
        )
        uow.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_empty_selection_activates_and_leaves_requests_pending(
        self, make_establishment, mock_auth_service
    ):
        """Selecting nothing is valid: the account opens, requests stay pending
        and no access-granted email goes out."""
        user = _make_user(
            role=UserRole.FIELD_WORKER, status=UserStatus.PENDING_VALIDATION
        )
        estab = make_establishment()
        uow = _make_approve_uow(user=user, relations=[_make_relation(estab.id)])
        service = AdminService(uow, mock_auth_service)

        with patch(
            "app.services.admin_service.send_access_granted_email",
            new_callable=AsyncMock,
        ) as mock_email:
            await service.approve_field_worker(user.id, [])

        uow.user_repo.update_status.assert_called_once_with(user.id, UserStatus.ACTIVE)
        uow.user_establishment_repo.update_status_for_ids.assert_not_called()
        uow.commit.assert_called_once()
        mock_email.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_establishments_still_activates(self, mock_auth_service):
        """A field worker without requests can still be let in."""
        user = _make_user(
            role=UserRole.FIELD_WORKER, status=UserStatus.PENDING_VALIDATION
        )
        uow = _make_approve_uow(user=user, relations=[])
        service = AdminService(uow, mock_auth_service)

        await service.approve_field_worker(user.id, [])

        uow.user_establishment_repo.update_status_for_ids.assert_not_called()
        uow.user_repo.update_status.assert_called_once_with(user.id, UserStatus.ACTIVE)

    @pytest.mark.asyncio
    async def test_unrequested_establishment_raises_error(
        self, make_establishment, mock_auth_service
    ):
        """The admin cannot approve an establishment the worker never asked for."""
        user = _make_user(
            role=UserRole.FIELD_WORKER, status=UserStatus.PENDING_VALIDATION
        )
        estab = make_establishment()
        uow = _make_approve_uow(user=user, relations=[_make_relation(estab.id)])
        service = AdminService(uow, mock_auth_service)

        with pytest.raises(UserEstablishmentNotFoundError):
            await service.approve_field_worker(user.id, [uuid.uuid4()])

        uow.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_non_field_worker_raises_error(self, mock_auth_service):
        """An invited admin must not be activated through this endpoint."""
        user = _make_user(role=UserRole.ADMIN, status=UserStatus.PENDING_VALIDATION)
        uow = _make_approve_uow(user=user, relations=[])
        service = AdminService(uow, mock_auth_service)

        with pytest.raises(BadRequestError):
            await service.approve_field_worker(user.id, [])

        uow.user_repo.update_status.assert_not_called()
        uow.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_non_pending_field_worker_raises_error(self, mock_auth_service):
        """Already resolved field workers cannot be re-approved."""
        user = _make_user(role=UserRole.FIELD_WORKER, status=UserStatus.ACTIVE)
        uow = _make_approve_uow(user=user, relations=[])
        service = AdminService(uow, mock_auth_service)

        with pytest.raises(BadRequestError):
            await service.approve_field_worker(user.id, [])

        uow.user_repo.update_status.assert_not_called()


class TestRejectFieldWorker:
    @pytest.mark.asyncio
    async def test_user_not_found_raises_error(self, mock_auth_service):
        uow = _make_approve_uow(user=None)
        service = AdminService(uow, mock_auth_service)

        with pytest.raises(UserNotFoundError):
            await service.reject_field_worker(uuid.uuid4())

    @pytest.mark.asyncio
    async def test_rejects_all_establishments_and_marks_inactive(
        self, make_establishment, mock_auth_service
    ):
        user = _make_user(
            role=UserRole.FIELD_WORKER, status=UserStatus.PENDING_VALIDATION
        )
        estab1 = make_establishment()
        estab2 = make_establishment()
        relations = [_make_relation(estab1.id), _make_relation(estab2.id)]
        uow = _make_approve_uow(user=user, relations=relations)
        service = AdminService(uow, mock_auth_service)

        await service.reject_field_worker(user.id)

        uow.user_establishment_repo.update_status_for_ids.assert_called_once_with(
            user.id, [estab1.id, estab2.id], UserEstablishmentStatus.REJECTED
        )
        uow.user_repo.update_status.assert_called_once_with(
            user.id, UserStatus.INACTIVE
        )
        uow.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_establishments_still_marks_inactive(self, mock_auth_service):
        user = _make_user(
            role=UserRole.FIELD_WORKER, status=UserStatus.PENDING_VALIDATION
        )
        uow = _make_approve_uow(user=user, relations=[])
        service = AdminService(uow, mock_auth_service)

        await service.reject_field_worker(user.id)

        uow.user_establishment_repo.update_status_for_ids.assert_not_called()
        uow.user_repo.update_status.assert_called_once_with(
            user.id, UserStatus.INACTIVE
        )
        uow.commit.assert_called_once()


def _make_pending_uow(
    users=None,
    total=0,
    establishment_ids_by_user=None,
    establishments=None,
    total_pending=0,
):
    uow = AsyncMock()
    users = users or []
    uow.user_repo.get_pending_establishments_page = AsyncMock(
        return_value=(users, total)
    )
    uow.user_establishment_repo.get_by_user_ids = AsyncMock(
        return_value=establishment_ids_by_user
        if establishment_ids_by_user is not None
        else {user.id: [] for user in users}
    )
    uow.establishment_repo.find_by_ids = AsyncMock(return_value=establishments or [])
    uow.user_repo.count_pending_establishments = AsyncMock(return_value=total_pending)
    return uow


class TestGetPendingEstablishmentRequests:
    @pytest.mark.asyncio
    async def test_hydrates_only_pending_establishments(
        self, mock_auth_service, make_establishment
    ):
        user = _make_user(role=UserRole.FIELD_WORKER)
        pending = make_establishment(name="Comedor Norte")
        uow = _make_pending_uow(
            users=[user],
            total=1,
            establishment_ids_by_user={user.id: [pending.id]},
            establishments=[pending],
            total_pending=4,
        )
        service = AdminService(uow, mock_auth_service)

        result, total_pending = await service.get_pending_establishment_requests(
            page=1, page_size=20
        )

        uow.user_establishment_repo.get_by_user_ids.assert_called_once_with(
            [user.id], UserEstablishmentStatus.PENDING
        )
        assert [e.id for e in result.items[0].establishments] == [pending.id]
        assert total_pending == 4

    @pytest.mark.asyncio
    async def test_counts_pending_relations_globally(self, mock_auth_service):
        uow = _make_pending_uow(users=[_make_user()], total=1, total_pending=37)
        service = AdminService(uow, mock_auth_service)

        _, total_pending = await service.get_pending_establishment_requests(
            page=2, page_size=20
        )

        uow.user_repo.count_pending_establishments.assert_called_once_with(
            search=None, establishment_id=None
        )
        assert total_pending == 37

    @pytest.mark.asyncio
    async def test_calculates_offset_correctly(self, mock_auth_service):
        uow = _make_pending_uow()
        service = AdminService(uow, mock_auth_service)

        await service.get_pending_establishment_requests(page=3, page_size=20)

        uow.user_repo.get_pending_establishments_page.assert_called_once_with(
            limit=20, offset=40, search=None, establishment_id=None
        )

    @pytest.mark.asyncio
    async def test_returns_pagination_metadata(self, mock_auth_service):
        users = [_make_user(role=UserRole.FIELD_WORKER) for _ in range(5)]
        uow = _make_pending_uow(users=users, total=45, total_pending=90)
        service = AdminService(uow, mock_auth_service)

        result, _ = await service.get_pending_establishment_requests(
            page=3, page_size=20
        )

        assert len(result.items) == 5
        assert result.total == 45
        assert result.page == 3
        assert result.page_size == 20
        assert result.total_pages == ceil(45 / 20)

    @pytest.mark.asyncio
    async def test_no_pending_requests_returns_empty_result(self, mock_auth_service):
        uow = _make_pending_uow()
        service = AdminService(uow, mock_auth_service)

        result, total_pending = await service.get_pending_establishment_requests(
            page=1, page_size=20
        )

        assert result.items == []
        assert result.total == 0
        assert result.total_pages == 0
        assert total_pending == 0
        uow.user_establishment_repo.get_by_user_ids.assert_not_called()

    @pytest.mark.asyncio
    async def test_forwards_search_and_establishment_filters(self, mock_auth_service):
        uow = _make_pending_uow()
        service = AdminService(uow, mock_auth_service)
        establishment_id = uuid.uuid4()

        await service.get_pending_establishment_requests(
            page=1, page_size=20, search="ana", establishment_id=establishment_id
        )

        uow.user_repo.get_pending_establishments_page.assert_called_once_with(
            limit=20, offset=0, search="ana", establishment_id=establishment_id
        )
        uow.user_repo.count_pending_establishments.assert_called_once_with(
            search="ana", establishment_id=establishment_id
        )

    @pytest.mark.asyncio
    async def test_strips_whitespace_from_search(self, mock_auth_service):
        uow = _make_pending_uow()
        service = AdminService(uow, mock_auth_service)

        await service.get_pending_establishment_requests(
            page=1, page_size=20, search="  ana  "
        )

        uow.user_repo.get_pending_establishments_page.assert_called_once_with(
            limit=20, offset=0, search="ana", establishment_id=None
        )

    @pytest.mark.asyncio
    async def test_whitespace_only_search_passes_none(self, mock_auth_service):
        uow = _make_pending_uow()
        service = AdminService(uow, mock_auth_service)

        await service.get_pending_establishment_requests(
            page=1, page_size=20, search="   "
        )

        uow.user_repo.get_pending_establishments_page.assert_called_once_with(
            limit=20, offset=0, search=None, establishment_id=None
        )
