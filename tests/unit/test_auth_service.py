import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.auth import LoginDomain, RefreshDomain
from app.domain.user import UserRole, UserStatus
from app.exceptions.domain_exceptions import (
    EstablishmentNotFoundError,
    InvalidCredentialsError,
    InvalidTokenError,
    UserAlreadyExistsError,
)
from app.schemas.auth_schema import (
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    RegisterFieldWorkerRequest,
)
from app.services.auth_service import AuthService


@pytest.fixture
def valid_refresh_request():
    return RefreshRequest(
        refresh_token="raw_refresh_token",
        device_id=str(uuid.uuid4()),
    )


@pytest.fixture
def make_active_token():
    """Return a factory for mock token rows returned by token_repo."""

    def _make(role: UserRole = UserRole.ADMIN):
        t = MagicMock()
        t.user_id = uuid.uuid4()
        t.role = role
        return t

    return _make


@pytest.fixture
def device_id():
    return uuid.uuid4()


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

        uow.user_repo.get_by_email = AsyncMock(return_value=existing_user)
        uow.establishment_repo.get_all_by_ids = AsyncMock(
            return_value=establishments or []
        )
        uow.user_repo.create = AsyncMock(return_value=make_user())
        uow.password_repo.create = AsyncMock()
        uow.user_establishment_repo.preset_relation = AsyncMock()

        uow.user_repo.get_by_email = AsyncMock(return_value=login_user or existing_user)
        uow.password_repo.get_by_user_id = AsyncMock(return_value=password_record)
        uow.token_repo.create = AsyncMock()

        uow.token_repo.get_active_refresh_token = AsyncMock(return_value=active_token)
        uow.token_repo.revoke = AsyncMock()

        uow.commit = AsyncMock()
        return uow

    return _make


@pytest.fixture
def mock_hash_password(monkeypatch):
    monkeypatch.setattr("app.services.auth_service.hash_password", lambda p: "hashed")


@pytest.fixture
def mock_security(monkeypatch):
    monkeypatch.setattr(
        "app.services.auth_service.verify_password",
        lambda plain, hashed: plain == "correct_password",
    )
    monkeypatch.setattr(
        "app.services.auth_service.create_access_token",
        lambda user_id, role: f"access.{role}.mocked",
    )
    monkeypatch.setattr(
        "app.services.auth_service.create_refresh_token",
        lambda: ("raw_refresh_token", "hashed_refresh_token"),
    )


@pytest.fixture
def mock_encode_refresh_token(monkeypatch):
    monkeypatch.setattr(
        "app.services.auth_service.encode_refresh_token",
        lambda token: "hashed_refresh_token",
    )


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


@pytest.fixture
def make_token():
    def _make(revoked: bool = False):
        t = MagicMock()
        t.revoked = revoked
        return t

    return _make


@pytest.fixture
def valid_register_request_obligatory_fields():
    return RegisterFieldWorkerRequest(
        email="field_worker@example.com",
        password="securepassword",
        name="Juan",
        last_name="Perez",
        establishments=[uuid.uuid4()],
    )


@pytest.fixture
def valid_register_request_all_fields():
    return RegisterFieldWorkerRequest(
        email="field_worker@example.com",
        password="securepassword",
        name="Juan",
        last_name="Perez",
        establishments=[uuid.uuid4()],
        locality="Caballito",
        description="User description and information.",
        contact_phone="2478100000",
    )


@pytest.fixture
def valid_login_request(device_id):
    return LoginRequest(
        email="user@test.com",
        password="correct_password",
        device_id=device_id,
    )


@pytest.fixture
def valid_logout_request():
    return LogoutRequest(
        refresh_token="raw_refresh_token",
        device_id=str(uuid.uuid4()),
    )


class TestRegisterFieldWorker:
    @pytest.mark.asyncio
    async def test_creates_field_worker_with_correct_role_and_status(
        self, make_uow, make_establishment, valid_register_request_all_fields
    ):
        establishment = make_establishment()
        uow = make_uow(establishments=[establishment])

        await AuthService(uow).register_field_worker(valid_register_request_all_fields)

        uow.user_repo.create.assert_called_once_with(
            email=valid_register_request_all_fields.email,
            name=valid_register_request_all_fields.name,
            last_name=valid_register_request_all_fields.last_name,
            role=UserRole.FIELD_WORKER,
            status=UserStatus.PENDING_VALIDATION,
            locality=valid_register_request_all_fields.locality,
            description=valid_register_request_all_fields.description,
            contact_phone=valid_register_request_all_fields.contact_phone,
        )

    @pytest.mark.asyncio
    async def test_registration_creates_password(
        self,
        make_uow,
        make_establishment,
        mock_hash_password,
        valid_register_request_obligatory_fields,
    ):
        establishment = make_establishment()
        uow = make_uow(establishments=[establishment])

        user = await AuthService(uow).register_field_worker(
            valid_register_request_obligatory_fields
        )

        uow.password_repo.create.assert_called_once_with(user.id, "hashed")

    @pytest.mark.asyncio
    async def test_registration_creates_one_relation_per_establishment(
        self, make_uow, make_establishment, valid_register_request_obligatory_fields
    ):
        establishments = [
            make_establishment(),
            make_establishment(),
            make_establishment(),
        ]
        valid_register_request_obligatory_fields.establishments = [
            e.id for e in establishments
        ]
        uow = make_uow(establishments=establishments)

        await AuthService(uow).register_field_worker(
            valid_register_request_obligatory_fields
        )

        assert uow.user_establishment_repo.preset_relation.call_count == 3

    @pytest.mark.asyncio
    async def test_raises_if_email_already_exists(
        self, make_uow, make_user, valid_register_request_obligatory_fields
    ):
        uow = make_uow(existing_user=make_user())

        with pytest.raises(UserAlreadyExistsError):
            await AuthService(uow).register_field_worker(
                valid_register_request_obligatory_fields
            )

        uow.user_repo.create.assert_not_called()
        uow.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_raises_if_establishment_not_found(
        self, make_uow, valid_register_request_obligatory_fields
    ):
        uow = make_uow()
        uow.establishment_repo.get_all_by_ids = AsyncMock(
            side_effect=EstablishmentNotFoundError(str(uuid.uuid4()))
        )

        with pytest.raises(EstablishmentNotFoundError):
            await AuthService(uow).register_field_worker(
                valid_register_request_obligatory_fields
            )

        uow.user_repo.create.assert_not_called()
        uow.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_optional_fields_are_not_required(
        self, make_uow, make_establishment, valid_register_request_obligatory_fields
    ):
        establishment = make_establishment()
        uow = make_uow(establishments=[establishment])
        await AuthService(uow).register_field_worker(
            valid_register_request_obligatory_fields
        )

        uow.user_repo.create.assert_called_once_with(
            email=valid_register_request_obligatory_fields.email,
            name=valid_register_request_obligatory_fields.name,
            last_name=valid_register_request_obligatory_fields.last_name,
            role=UserRole.FIELD_WORKER,
            status=UserStatus.PENDING_VALIDATION,
            locality=None,
            description=None,
            contact_phone=None,
        )


class TestLoginSuccess:
    @pytest.mark.asyncio
    async def test_returns_login_domain(
        self,
        make_uow,
        make_login_user,
        make_password_record,
        valid_login_request,
        mock_security,
    ):
        user = make_login_user()
        uow = make_uow(login_user=user, password_record=make_password_record(user))

        result = await AuthService(uow).login(valid_login_request)

        assert isinstance(result, LoginDomain)

    @pytest.mark.asyncio
    async def test_access_token_issued(
        self,
        make_uow,
        make_login_user,
        make_password_record,
        valid_login_request,
        mock_security,
    ):
        user = make_login_user()
        uow = make_uow(login_user=user, password_record=make_password_record(user))

        result = await AuthService(uow).login(valid_login_request)

        assert result.access_token == f"access.{user.role}.mocked"

    @pytest.mark.asyncio
    async def test_refresh_token_issued(
        self,
        make_uow,
        make_login_user,
        make_password_record,
        valid_login_request,
        mock_security,
    ):
        user = make_login_user()
        uow = make_uow(login_user=user, password_record=make_password_record(user))

        result = await AuthService(uow).login(valid_login_request)

        assert result.refresh_token == "raw_refresh_token"

    @pytest.mark.asyncio
    async def test_token_persisted_and_committed(
        self,
        make_uow,
        make_login_user,
        make_password_record,
        valid_login_request,
        mock_security,
    ):
        user = make_login_user()
        uow = make_uow(login_user=user, password_record=make_password_record(user))

        await AuthService(uow).login(valid_login_request)

        uow.token_repo.create.assert_awaited_once()
        uow.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_user_domain_fields_mapped_correctly(
        self,
        make_uow,
        make_login_user,
        make_password_record,
        valid_login_request,
        mock_security,
    ):
        user = make_login_user()
        uow = make_uow(login_user=user, password_record=make_password_record(user))

        result = await AuthService(uow).login(valid_login_request)

        assert result.user.id == user.id
        assert result.user.email == str(user.email)
        assert result.user.name == user.name
        assert result.user.last_name == user.last_name
        assert result.user.role == user.role
        assert result.user.status == user.status


class TestLoginUnknownEmail:
    @pytest.mark.asyncio
    async def test_raises_invalid_credentials(
        self, make_uow, valid_login_request, mock_security
    ):
        uow = make_uow(login_user=None)

        with pytest.raises(InvalidCredentialsError):
            await AuthService(uow).login(valid_login_request)

    @pytest.mark.asyncio
    async def test_does_not_query_password(
        self, make_uow, valid_login_request, mock_security
    ):
        uow = make_uow(login_user=None)

        with pytest.raises(InvalidCredentialsError):
            await AuthService(uow).login(valid_login_request)

        uow.password_repo.get_by_user_id.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_does_not_commit(self, make_uow, valid_login_request, mock_security):
        uow = make_uow(login_user=None)

        with pytest.raises(InvalidCredentialsError):
            await AuthService(uow).login(valid_login_request)

        uow.commit.assert_not_awaited()


class TestLoginMissingPasswordRecord:
    @pytest.mark.asyncio
    async def test_raises_invalid_credentials(
        self, make_uow, make_login_user, valid_login_request, mock_security
    ):
        user = make_login_user()
        uow = make_uow(login_user=user, password_record=None)

        with pytest.raises(InvalidCredentialsError):
            await AuthService(uow).login(valid_login_request)

    @pytest.mark.asyncio
    async def test_does_not_commit(
        self, make_uow, make_login_user, valid_login_request, mock_security
    ):
        user = make_login_user()
        uow = make_uow(login_user=user, password_record=None)

        with pytest.raises(InvalidCredentialsError):
            await AuthService(uow).login(valid_login_request)

        uow.commit.assert_not_awaited()


class TestLoginWrongPassword:
    @pytest.mark.asyncio
    async def test_raises_invalid_credentials(
        self, make_uow, make_login_user, make_password_record, device_id, mock_security
    ):
        user = make_login_user()
        uow = make_uow(login_user=user, password_record=make_password_record(user))
        bad_request = LoginRequest(
            email=user.email, password="wrong_password", device_id=device_id
        )

        with pytest.raises(InvalidCredentialsError):
            await AuthService(uow).login(bad_request)

    @pytest.mark.asyncio
    async def test_does_not_commit(
        self, make_uow, make_login_user, make_password_record, device_id, mock_security
    ):
        user = make_login_user()
        uow = make_uow(login_user=user, password_record=make_password_record(user))
        bad_request = LoginRequest(
            email=user.email, password="wrong_password", device_id=device_id
        )

        with pytest.raises(InvalidCredentialsError):
            await AuthService(uow).login(bad_request)

        uow.commit.assert_not_awaited()


class TestLoginErrorMessageConsistency:
    @pytest.mark.asyncio
    async def test_unknown_email_and_wrong_password_same_exception(
        self, make_uow, make_login_user, make_password_record, device_id, mock_security
    ):
        user = make_login_user()
        uow_unknown = make_uow(login_user=None)
        uow_wrong_pw = make_uow(
            login_user=user, password_record=make_password_record(user)
        )

        req_unknown = LoginRequest(
            email="ghost@x.com", password="any", device_id=device_id
        )
        req_wrong = LoginRequest(
            email=user.email, password="wrong_password", device_id=device_id
        )

        with pytest.raises(InvalidCredentialsError) as exc_unknown:
            await AuthService(uow_unknown).login(req_unknown)

        with pytest.raises(InvalidCredentialsError) as exc_wrong:
            await AuthService(uow_wrong_pw).login(req_wrong)

        assert type(exc_unknown.value) is type(exc_wrong.value)
        assert str(exc_unknown.value) == str(exc_wrong.value)


class TestLogoutSuccess:
    @pytest.mark.asyncio
    async def test_revokes_token(
        self, make_uow, make_token, valid_logout_request, mock_encode_refresh_token
    ):
        token = make_token()
        uow = make_uow(active_token=token)

        await AuthService(uow).logout(valid_logout_request)

        uow.token_repo.revoke.assert_called_once_with(token)

    @pytest.mark.asyncio
    async def test_commits_after_revoke(
        self, make_uow, make_token, valid_logout_request, mock_encode_refresh_token
    ):
        uow = make_uow(active_token=make_token())

        await AuthService(uow).logout(valid_logout_request)

        uow.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_queries_with_encoded_token_and_device_id(
        self, make_uow, make_token, valid_logout_request, mock_encode_refresh_token
    ):
        uow = make_uow(active_token=make_token())

        await AuthService(uow).logout(valid_logout_request)

        uow.token_repo.get_active_refresh_token.assert_awaited_once_with(
            "hashed_refresh_token", valid_logout_request.device_id
        )


class TestLogoutInvalidToken:
    @pytest.mark.asyncio
    async def test_raises_invalid_token_error(
        self, make_uow, valid_logout_request, mock_encode_refresh_token
    ):
        uow = make_uow(active_token=None)

        with pytest.raises(InvalidTokenError):
            await AuthService(uow).logout(valid_logout_request)

    @pytest.mark.asyncio
    async def test_does_not_revoke(
        self, make_uow, valid_logout_request, mock_encode_refresh_token
    ):
        uow = make_uow(active_token=None)

        with pytest.raises(InvalidTokenError):
            await AuthService(uow).logout(valid_logout_request)

        uow.token_repo.revoke.assert_not_called()

    @pytest.mark.asyncio
    async def test_does_not_commit(
        self, make_uow, valid_logout_request, mock_encode_refresh_token
    ):
        uow = make_uow(active_token=None)

        with pytest.raises(InvalidTokenError):
            await AuthService(uow).logout(valid_logout_request)

        uow.commit.assert_not_awaited()


class TestRefreshSuccess:
    @pytest.mark.asyncio
    async def test_returns_refresh_domain(
        self,
        make_uow,
        make_active_token,
        valid_refresh_request,
        mock_security,
        mock_encode_refresh_token,
    ):
        token = make_active_token()
        uow = make_uow(active_token=token)

        result = await AuthService(uow).refresh(valid_refresh_request)

        assert isinstance(result, RefreshDomain)

    @pytest.mark.asyncio
    async def test_new_access_token_issued(
        self,
        make_uow,
        make_active_token,
        valid_refresh_request,
        mock_security,
        mock_encode_refresh_token,
    ):
        token = make_active_token(role=UserRole.ADMIN)
        uow = make_uow(active_token=token)

        result = await AuthService(uow).refresh(valid_refresh_request)

        assert result.access_token == f"access.{UserRole.ADMIN}.mocked"

    @pytest.mark.asyncio
    async def test_new_raw_refresh_token_returned(
        self,
        make_uow,
        make_active_token,
        valid_refresh_request,
        mock_security,
        mock_encode_refresh_token,
    ):
        uow = make_uow(active_token=make_active_token())

        result = await AuthService(uow).refresh(valid_refresh_request)

        assert result.refresh_token == "raw_refresh_token"

    @pytest.mark.asyncio
    async def test_old_token_revoked(
        self,
        make_uow,
        make_active_token,
        valid_refresh_request,
        mock_security,
        mock_encode_refresh_token,
    ):
        token = make_active_token()
        uow = make_uow(active_token=token)

        await AuthService(uow).refresh(valid_refresh_request)

        uow.token_repo.revoke.assert_called_once_with(token)

    @pytest.mark.asyncio
    async def test_new_token_persisted(
        self,
        make_uow,
        make_active_token,
        valid_refresh_request,
        mock_security,
        mock_encode_refresh_token,
    ):
        token = make_active_token()
        uow = make_uow(active_token=token)

        await AuthService(uow).refresh(valid_refresh_request)

        uow.token_repo.create.assert_awaited_once_with(
            user_id=token.user_id,
            token_hash="hashed_refresh_token",
            device_id=valid_refresh_request.device_id,
            role=token.role,
        )

    @pytest.mark.asyncio
    async def test_commits_after_rotation(
        self,
        make_uow,
        make_active_token,
        valid_refresh_request,
        mock_security,
        mock_encode_refresh_token,
    ):
        uow = make_uow(active_token=make_active_token())

        await AuthService(uow).refresh(valid_refresh_request)

        uow.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_queries_with_encoded_token_and_device_id(
        self,
        make_uow,
        make_active_token,
        valid_refresh_request,
        mock_security,
        mock_encode_refresh_token,
    ):
        uow = make_uow(active_token=make_active_token())

        await AuthService(uow).refresh(valid_refresh_request)

        uow.token_repo.get_active_refresh_token.assert_awaited_once_with(
            "hashed_refresh_token", valid_refresh_request.device_id
        )


class TestRefreshInvalidToken:
    @pytest.mark.asyncio
    async def test_raises_invalid_credentials(
        self,
        make_uow,
        valid_refresh_request,
        mock_encode_refresh_token,
    ):
        uow = make_uow(active_token=None)

        with pytest.raises(InvalidCredentialsError):
            await AuthService(uow).refresh(valid_refresh_request)

    @pytest.mark.asyncio
    async def test_does_not_revoke(
        self,
        make_uow,
        valid_refresh_request,
        mock_encode_refresh_token,
    ):
        uow = make_uow(active_token=None)

        with pytest.raises(InvalidCredentialsError):
            await AuthService(uow).refresh(valid_refresh_request)

        uow.token_repo.revoke.assert_not_called()

    @pytest.mark.asyncio
    async def test_does_not_create_new_token(
        self,
        make_uow,
        valid_refresh_request,
        mock_encode_refresh_token,
    ):
        uow = make_uow(active_token=None)

        with pytest.raises(InvalidCredentialsError):
            await AuthService(uow).refresh(valid_refresh_request)

        uow.token_repo.create.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_does_not_commit(
        self,
        make_uow,
        valid_refresh_request,
        mock_encode_refresh_token,
    ):
        uow = make_uow(active_token=None)

        with pytest.raises(InvalidCredentialsError):
            await AuthService(uow).refresh(valid_refresh_request)

        uow.commit.assert_not_awaited()
