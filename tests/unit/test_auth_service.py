import uuid
from unittest.mock import AsyncMock

import pytest

from app.exceptions.domain_exceptions import (
    EstablishmentNotFoundError,
    UserAlreadyExistsError,
)
from app.models.user import UserRole, UserStatus
from app.schemas.auth_schema import RegisterManagerRequest
from app.services.auth_service import AuthService


@pytest.fixture
def make_uow(make_user):
    def _make(existing_user=None, establishments=None):
        uow = AsyncMock()
        uow.user_repo.get_by_email = AsyncMock(return_value=existing_user)
        uow.establishment_repo.get_by_ids = AsyncMock(return_value=establishments or [])
        uow.user_repo.create = AsyncMock(return_value=make_user())
        uow.password_repo.create = AsyncMock()
        uow.user_establishment_repo.preset_relation = AsyncMock()
        uow.commit = AsyncMock()
        return uow

    return _make


@pytest.fixture
def mock_hash_password(monkeypatch):
    monkeypatch.setattr("app.services.auth_service.hash_password", lambda p: "hashed")


@pytest.fixture
def valid_request():
    return RegisterManagerRequest(
        email="manager@example.com",
        password="securepassword",
        name="Juan",
        last_name="Perez",
        establishments=[uuid.uuid4()],
    )


class TestRegisterManager:
    @pytest.mark.asyncio
    async def test_creates_manager_with_correct_role_and_status(
        self, make_uow, make_establishment, valid_request
    ):
        establishment = make_establishment()
        uow = make_uow(establishments=[establishment])
        service = AuthService(uow)

        await service.register_manager(valid_request)

        uow.user_repo.create.assert_called_once_with(
            email=valid_request.email,
            name=valid_request.name,
            last_name=valid_request.last_name,
            role=UserRole.ESTABLISHMENT_MANAGER,
            status=UserStatus.PENDING_VALIDATION,
        )

    @pytest.mark.asyncio
    async def test_registration_creates_password(
        self, make_uow, make_establishment, mock_hash_password, valid_request
    ):
        establishment = make_establishment()
        uow = make_uow(establishments=[establishment])
        service = AuthService(uow)

        user = await service.register_manager(valid_request)

        uow.password_repo.create.assert_called_once_with(user.id, "hashed")

    @pytest.mark.asyncio
    async def test_registration_creates_one_relation_per_establishment(
        self, make_uow, make_establishment, valid_request
    ):
        establishments = [
            make_establishment(),
            make_establishment(),
            make_establishment(),
        ]
        valid_request.establishments = [e.id for e in establishments]
        uow = make_uow(establishments=establishments)
        service = AuthService(uow)

        await service.register_manager(valid_request)

        assert uow.user_establishment_repo.preset_relation.call_count == 3

    @pytest.mark.asyncio
    async def test_raises_if_email_already_exists(
        self, make_uow, make_user, valid_request
    ):
        uow = make_uow(existing_user=make_user())
        service = AuthService(uow)

        with pytest.raises(UserAlreadyExistsError):
            await service.register_manager(valid_request)

        uow.user_repo.create.assert_not_called()
        uow.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_raises_if_establishment_not_found(self, make_uow, valid_request):
        uow = make_uow()
        uow.establishment_repo.get_by_ids = AsyncMock(
            side_effect=EstablishmentNotFoundError(str(uuid.uuid4()))
        )
        service = AuthService(uow)

        with pytest.raises(EstablishmentNotFoundError):
            await service.register_manager(valid_request)

        uow.user_repo.create.assert_not_called()
        uow.commit.assert_not_called()
