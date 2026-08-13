import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.user import UserStatus
from app.exceptions.domain_exceptions import InvalidTokenError, UserNotFoundError
from app.schemas.auth.auth_schema import (
    RegisterFieldWorkerRequest,
    ResendVerificationRequest,
    VerifyEmailRequest,
)
from app.services.auth.auth_service import AuthService


@pytest.fixture
def valid_verify_request():
    return VerifyEmailRequest(token="raw_verification_token")


@pytest.fixture
def valid_resend_request():
    return ResendVerificationRequest(email="user@test.com")


@pytest.fixture
def make_verification_token():
    def _make():
        t = MagicMock()
        t.user_id = uuid.uuid4()
        t.expires_at = MagicMock()
        return t

    return _make


@pytest.fixture
def register_field_worker_request(make_establishment):
    """A ready-to-use RegisterFieldWorkerRequest with one establishment."""
    establishment = make_establishment()
    return RegisterFieldWorkerRequest(
        email="worker@test.com",
        password="securepassword",
        name="Juan",
        last_name="Perez",
        establishments=[establishment.id],
    ), establishment


@pytest.fixture
def make_uow_verification(make_uow, make_verification_token):
    def _make(
        existing_user=None,
        establishments=None,
        login_user=None,
        password_record=None,
        active_token=None,
        active_verification_token=None,
        committed_token=None,
    ):
        uow = make_uow(
            existing_user=existing_user,
            establishments=establishments,
            login_user=login_user,
            password_record=password_record,
            active_token=active_token,
        )
        uow.email_verification_repo = AsyncMock()
        uow.email_verification_repo.get_active_token = AsyncMock(
            return_value=active_verification_token
        )
        uow.email_verification_repo.create = AsyncMock(
            return_value=committed_token or make_verification_token()
        )
        uow.email_verification_repo.mark_used = AsyncMock()
        uow.email_verification_repo.revoke_active_for_user = AsyncMock(return_value=1)
        uow.user_repo.get_by_id = AsyncMock(return_value=login_user)
        return uow

    return _make


# ---------------------------------------------------------------------------
# Monkeypatch fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_encode_verification_token(monkeypatch):
    monkeypatch.setattr(
        "app.services.auth.auth_service.hash_token",
        lambda token: "hashed_verification_token",
    )


@pytest.fixture
def mock_create_email_verification_token(monkeypatch):
    monkeypatch.setattr(
        "app.services.auth.auth_service.create_email_verification_token",
        lambda: ("raw_verification_token", "hashed_verification_token"),
    )


@pytest.fixture
def mock_send_verification_email(monkeypatch):
    mock_fn = AsyncMock()
    monkeypatch.setattr(
        "app.services.auth.auth_service.send_verification_email", mock_fn
    )
    return mock_fn


@pytest.fixture
def mock_build_verification_deeplink(monkeypatch):
    monkeypatch.setattr(
        "app.services.auth.auth_service.build_verification_deeplink",
        lambda token: f"https://example.com/verify?token={token}",
    )


@pytest.fixture
def mock_hash_password(monkeypatch):
    monkeypatch.setattr(
        "app.services.auth.auth_service.hash_password", lambda p: "hashed"
    )


@pytest.fixture
def email_mocks(
    mock_create_email_verification_token,
    mock_build_verification_deeplink,
    mock_send_verification_email,
):
    """Groups the three email-related patches used by resend and registration tests."""
    return mock_send_verification_email  # caller only needs the send mock returned


def _make_unverified_user_uow(make_uow_verification, make_login_user, email):
    user = make_login_user()
    user.is_email_verified = False
    uow = make_uow_verification(login_user=user)
    uow.user_repo.get_by_email = AsyncMock(return_value=user)
    return uow, user


def _make_verified_user_uow(make_uow_verification, make_login_user, email):
    user = make_login_user()
    user.is_email_verified = True
    uow = make_uow_verification(login_user=user)
    uow.user_repo.get_by_email = AsyncMock(return_value=user)
    return uow, user


class TestVerifyEmailSuccess:
    @pytest.fixture(autouse=True)
    def setup(
        self,
        make_uow_verification,
        make_verification_token,
        make_login_user,
        mock_encode_verification_token,
    ):
        self.token = make_verification_token()
        self.uow = make_uow_verification(
            active_verification_token=self.token,
            login_user=make_login_user(),
        )
        self.uow.user_repo.update_email_verification = AsyncMock()

    @pytest.mark.asyncio
    async def test_queries_with_encoded_token(self, valid_verify_request):
        await AuthService(self.uow).verify_email(valid_verify_request.token)

        self.uow.email_verification_repo.get_active_token.assert_awaited_once_with(
            "hashed_verification_token"
        )

    @pytest.mark.asyncio
    async def test_marks_token_as_used(self, valid_verify_request):
        await AuthService(self.uow).verify_email(valid_verify_request.token)

        self.uow.email_verification_repo.mark_used.assert_awaited_once_with(self.token)

    @pytest.mark.asyncio
    async def test_calls_repository_to_update_email_verification(
        self, valid_verify_request
    ):
        """Asserts the service delegates the database update to the repository layer."""
        await AuthService(self.uow).verify_email(valid_verify_request.token)

        self.uow.user_repo.update_email_verification.assert_awaited_once_with(
            self.token.user_id
        )

    @pytest.mark.asyncio
    async def test_commits(self, valid_verify_request):
        await AuthService(self.uow).verify_email(valid_verify_request.token)

        self.uow.commit.assert_awaited_once()


class TestVerifyEmailInvalidToken:
    @pytest.fixture(autouse=True)
    def setup(self, make_uow_verification, mock_encode_verification_token):
        # get_active_token returns None → token not found or already used
        self.uow = make_uow_verification(active_verification_token=None)

    @pytest.mark.asyncio
    async def test_raises_invalid_token_error(self, valid_verify_request):
        with pytest.raises(InvalidTokenError):
            await AuthService(self.uow).verify_email(valid_verify_request.token)

    @pytest.mark.asyncio
    async def test_error_message_informs_user(self, valid_verify_request):
        with pytest.raises(InvalidTokenError) as exc:
            await AuthService(self.uow).verify_email(valid_verify_request.token)

        assert "invalid" in str(exc.value) or "expired" in str(exc.value)

    @pytest.mark.asyncio
    async def test_does_not_mark_token_as_used(self, valid_verify_request):
        with pytest.raises(InvalidTokenError):
            await AuthService(self.uow).verify_email(valid_verify_request.token)

        self.uow.email_verification_repo.mark_used.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_does_not_fetch_user(self, valid_verify_request):
        with pytest.raises(InvalidTokenError):
            await AuthService(self.uow).verify_email(valid_verify_request.token)

        self.uow.user_repo.get_by_id.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_does_not_commit(self, valid_verify_request):
        with pytest.raises(InvalidTokenError):
            await AuthService(self.uow).verify_email(valid_verify_request.token)

        self.uow.commit.assert_not_awaited()


class TestResendVerificationEmailSuccess:
    @pytest.fixture(autouse=True)
    def setup(
        self, make_uow_verification, make_login_user, email_mocks, valid_resend_request
    ):
        self.mock_send = email_mocks
        self.uow, self.user = _make_unverified_user_uow(
            make_uow_verification, make_login_user, valid_resend_request.email
        )

    @pytest.mark.asyncio
    async def test_queries_user_by_email(self, valid_resend_request):
        await AuthService(self.uow).resend_verification_email(
            valid_resend_request.email
        )

        self.uow.user_repo.get_by_email.assert_awaited_once_with(
            valid_resend_request.email
        )

    @pytest.mark.asyncio
    async def test_revokes_old_tokens(self, valid_resend_request):
        await AuthService(self.uow).resend_verification_email(
            valid_resend_request.email
        )

        self.uow.email_verification_repo.revoke_active_for_user.assert_awaited_once_with(
            self.user.id
        )

    @pytest.mark.asyncio
    async def test_creates_new_token(self, valid_resend_request):
        await AuthService(self.uow).resend_verification_email(
            valid_resend_request.email
        )

        self.uow.email_verification_repo.create.assert_awaited_once()
        call_args = self.uow.email_verification_repo.create.await_args
        assert call_args[0][0] == self.user.id
        assert call_args[0][1] == "hashed_verification_token"

    @pytest.mark.asyncio
    async def test_sends_verification_email(self, valid_resend_request):
        await AuthService(self.uow).resend_verification_email(
            valid_resend_request.email
        )

        self.mock_send.assert_awaited_once_with(
            self.user.email,
            "https://example.com/verify?token=raw_verification_token",
            self.uow.email_verification_repo.create.return_value.expires_at,
        )

    @pytest.mark.asyncio
    async def test_commits(self, valid_resend_request):
        await AuthService(self.uow).resend_verification_email(
            valid_resend_request.email
        )

        self.uow.commit.assert_awaited_once()


class TestResendVerificationEmailAlreadyVerified:
    @pytest.fixture(autouse=True)
    def setup(
        self, make_uow_verification, make_login_user, email_mocks, valid_resend_request
    ):
        self.mock_send = email_mocks
        self.uow, self.user = _make_verified_user_uow(
            make_uow_verification, make_login_user, valid_resend_request.email
        )

    @pytest.mark.asyncio
    async def test_does_not_revoke_tokens(self, valid_resend_request):
        await AuthService(self.uow).resend_verification_email(
            valid_resend_request.email
        )

        self.uow.email_verification_repo.revoke_active_for_user.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_does_not_create_new_token(self, valid_resend_request):
        await AuthService(self.uow).resend_verification_email(
            valid_resend_request.email
        )

        self.uow.email_verification_repo.create.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_does_not_send_email(self, valid_resend_request):
        await AuthService(self.uow).resend_verification_email(
            valid_resend_request.email
        )

        self.mock_send.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_does_not_commit(self, valid_resend_request):
        await AuthService(self.uow).resend_verification_email(
            valid_resend_request.email
        )

        self.uow.commit.assert_not_awaited()


class TestResendVerificationEmailUserNotFound:
    @pytest.fixture(autouse=True)
    def setup(self, make_uow_verification):
        self.uow = make_uow_verification()
        self.uow.user_repo.get_by_email = AsyncMock(return_value=None)

    @pytest.mark.asyncio
    async def test_raises_user_not_found(self, valid_resend_request):
        with pytest.raises(UserNotFoundError):
            await AuthService(self.uow).resend_verification_email(
                valid_resend_request.email
            )

    @pytest.mark.asyncio
    async def test_does_not_revoke_tokens(self, valid_resend_request):
        with pytest.raises(UserNotFoundError):
            await AuthService(self.uow).resend_verification_email(
                valid_resend_request.email
            )

        self.uow.email_verification_repo.revoke_active_for_user.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_does_not_commit(self, valid_resend_request):
        with pytest.raises(UserNotFoundError):
            await AuthService(self.uow).resend_verification_email(
                valid_resend_request.email
            )

        self.uow.commit.assert_not_awaited()


class TestRegistrationCreatesVerificationToken:
    @pytest.fixture(autouse=True)
    def setup(
        self, make_uow_verification, make_establishment, mock_hash_password, email_mocks
    ):
        self.mock_send = email_mocks
        establishment = make_establishment()
        self.uow = make_uow_verification(establishments=[establishment])
        self.uow.user_repo.get_by_email = AsyncMock(return_value=None)
        self.request = RegisterFieldWorkerRequest(
            email="worker@test.com",
            password="securepassword",
            name="Juan",
            last_name="Perez",
            establishments=[establishment.id],
        )

    @pytest.mark.asyncio
    async def test_creates_verification_token(self):
        await AuthService(self.uow).register_field_worker(self.request)

        self.uow.email_verification_repo.create.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_token_expiration_is_24_hours(self):
        await AuthService(self.uow).register_field_worker(self.request)

        expires_delta = self.uow.email_verification_repo.create.await_args.kwargs[
            "expires_delta"
        ]
        assert expires_delta.total_seconds() == 86400

    @pytest.mark.asyncio
    async def test_sends_verification_email(self):
        await AuthService(self.uow).register_field_worker(self.request)

        self.mock_send.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_new_user_status_is_pending_validation(self):
        await AuthService(self.uow).register_field_worker(self.request)

        self.uow.user_repo.create.assert_called_once()
        call_kwargs = self.uow.user_repo.create.call_args.kwargs
        assert call_kwargs.get("status") == UserStatus.PENDING_VALIDATION
