import os
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.exceptions.domain_exceptions import EstablishmentNotFoundError
from app.models import UserRole, UserStatus

os.environ.setdefault("OTEL_SDK_DISABLED", "true")


@pytest.fixture
def stub_establishment_lookup():
    """Wire ``establishment_repo.get_by_id_or_raise`` on a mocked UoW.

    Mirrors the real repository: passing None makes the lookup raise instead of
    returning it, so services under test take the same branch they do in
    production rather than receiving a truthy AsyncMock.
    """

    def _stub(uow, establishment):
        uow.establishment_repo.get_by_id_or_raise = AsyncMock(
            return_value=establishment,
            side_effect=(
                None
                if establishment is not None
                else EstablishmentNotFoundError(str(uuid.uuid4()))
            ),
        )

    return _stub


@pytest.fixture
def make_establishment():
    def _make(name: str = "Centro A", formatted_address: str = "Calle 1"):
        e = MagicMock()
        e.id = uuid.uuid4()
        e.name = name
        e.formatted_address = formatted_address
        e.latitude = -34.6
        e.longitude = -58.4
        e.place_id = "place-test-001"
        e.city = "Buenos Aires"
        e.province = "Buenos Aires"
        return e

    return _make


@pytest.fixture
def make_user():
    def _make():
        u = MagicMock()
        u.id = uuid.uuid4()
        u.role = UserRole.FIELD_WORKER
        u.status = UserStatus.PENDING_VALIDATION
        return u

    return _make


@pytest.fixture
def make_uow(make_user):
    def _make(
        existing_user=None,
        establishments=None,
        login_user=None,
        password_record=None,
        active_token=None,
    ):
        uow = AsyncMock()

        uow.user_repo.get_by_email = AsyncMock(return_value=login_user or existing_user)
        uow.establishment_repo.get_all_by_ids = AsyncMock(
            return_value=establishments or []
        )
        uow.user_repo.create = AsyncMock(return_value=make_user())
        uow.password_repo.create = AsyncMock()
        uow.password_repo.get_by_user_id = AsyncMock(return_value=password_record)
        uow.user_establishment_repo.preset_relation = AsyncMock()
        uow.token_repo.create = AsyncMock()
        uow.token_repo.get_active_refresh_token = AsyncMock(return_value=active_token)
        uow.token_repo.revoke = AsyncMock()
        uow.commit = AsyncMock()

        return uow

    return _make


@pytest.fixture
def make_login_user():
    def _make(
        role: UserRole = UserRole.ADMIN,
        status: UserStatus = UserStatus.ACTIVE,
    ):
        u = MagicMock()
        u.id = uuid.uuid4()
        u.email = "user@test.com"
        u.name = "Test"
        u.last_name = "User"
        u.role = role
        u.status = status
        u.establishments = []
        return u

    return _make


@pytest.fixture
def make_password_record():
    def _make(user):
        p = MagicMock()
        p.user_id = user.id
        p.password_hashed = "hashed_correct_password"
        return p

    return _make
