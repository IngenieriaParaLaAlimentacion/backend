import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.user import UserRole, UserStatus
from app.exceptions.domain_exceptions import (
    InvalidRecoveryTokenError,
    InvalidTokenError,
    PasswordNotFoundError,
    RecoveryTokenExpiredError,
    RecoveryTokenUsedError,
)
from app.schemas.auth.auth_schema import (
    PasswordRecoveryConfirmRequest,
    PasswordRecoveryRequest,
)
from app.services.auth.auth_service import AuthService


@pytest.fixture
def valid_confirm_request():
    return PasswordRecoveryConfirmRequest(
        token="raw_recovery_token",
        new_password="newpassword123",
    )


@pytest.fixture
def make_recovery_token():
    def _make(used=False, expires_in=timedelta(hours=1), user_id=None):
        t = MagicMock()
        t.user_id = user_id or uuid.uuid4()
        t.used = used
        t.expires_at = datetime.now(timezone.utc) + expires_in
        return t

    return _make


@pytest.fixture
def make_uow_recovery(make_uow, make_recovery_token, make_login_user):
    def _make(active_recovery_token=None, password_record=None, user=None):
        resolved_user = user if user is not None else make_login_user()
        uow = make_uow(password_record=password_record, login_user=resolved_user)
        uow.user_repo.get_by_id = AsyncMock(return_value=resolved_user)
        uow.password_recovery_repo.get_by_hash = AsyncMock(
            return_value=active_recovery_token
        )
        uow.password_recovery_repo.mark_used = AsyncMock()
        uow.password_recovery_repo.revoke_active_for_user = AsyncMock()
        uow.password_recovery_repo.create = AsyncMock(
            return_value=MagicMock(expires_at=datetime.now(timezone.utc))
        )
        uow.token_repo.revoke_all_by_user_id = AsyncMock()
        return uow

    return _make


@pytest.fixture
def mock_encode_recovery_token(monkeypatch):
    monkeypatch.setattr(
        "app.services.auth.auth_service.hash_token",
        lambda token: "hashed_recovery_token",
    )


@pytest.fixture
def mock_hash_password_recovery(monkeypatch):
    monkeypatch.setattr(
        "app.services.auth.auth_service.hash_password",
        lambda p: f"hashed_{p}",
    )


class TestConfirmPasswordRecoverySuccess:
    async def test_queries_with_encoded_token(
        self,
        make_uow_recovery,
        make_recovery_token,
        make_password_record,
        make_login_user,
        valid_confirm_request,
        mock_encode_recovery_token,
        mock_hash_password_recovery,
    ):
        token = make_recovery_token()
        user = make_login_user()
        uow = make_uow_recovery(
            active_recovery_token=token,
            password_record=make_password_record(user),
        )

        await AuthService(uow).confirm_password_recovery(valid_confirm_request)

        uow.password_recovery_repo.get_by_hash.assert_awaited_once_with(
            "hashed_recovery_token"
        )

    async def test_updates_password_hash(
        self,
        make_uow_recovery,
        make_recovery_token,
        make_password_record,
        make_login_user,
        valid_confirm_request,
        mock_encode_recovery_token,
        mock_hash_password_recovery,
    ):
        token = make_recovery_token()
        user = make_login_user()
        password_record = make_password_record(user)
        uow = make_uow_recovery(
            active_recovery_token=token,
            password_record=password_record,
        )

        await AuthService(uow).confirm_password_recovery(valid_confirm_request)

        assert password_record.password_hashed == "hashed_newpassword123"

    async def test_marks_token_as_used(
        self,
        make_uow_recovery,
        make_recovery_token,
        make_password_record,
        make_login_user,
        valid_confirm_request,
        mock_encode_recovery_token,
        mock_hash_password_recovery,
    ):
        token = make_recovery_token()
        user = make_login_user()
        uow = make_uow_recovery(
            active_recovery_token=token,
            password_record=make_password_record(user),
        )

        await AuthService(uow).confirm_password_recovery(valid_confirm_request)

        uow.password_recovery_repo.mark_used.assert_awaited_once_with(token)

    async def test_revokes_all_user_tokens(
        self,
        make_uow_recovery,
        make_recovery_token,
        make_password_record,
        make_login_user,
        valid_confirm_request,
        mock_encode_recovery_token,
        mock_hash_password_recovery,
    ):
        token = make_recovery_token()
        user = make_login_user()
        uow = make_uow_recovery(
            active_recovery_token=token,
            password_record=make_password_record(user),
        )

        await AuthService(uow).confirm_password_recovery(valid_confirm_request)

        uow.token_repo.revoke_all_by_user_id.assert_awaited_once_with(token.user_id)

    async def test_commits(
        self,
        make_uow_recovery,
        make_recovery_token,
        make_password_record,
        make_login_user,
        valid_confirm_request,
        mock_encode_recovery_token,
        mock_hash_password_recovery,
    ):
        token = make_recovery_token()
        user = make_login_user()
        uow = make_uow_recovery(
            active_recovery_token=token,
            password_record=make_password_record(user),
        )

        await AuthService(uow).confirm_password_recovery(valid_confirm_request)

        uow.commit.assert_awaited_once()


class TestConfirmPasswordRecoveryInvalidToken:
    async def test_raises_invalid_token_error(
        self,
        make_uow_recovery,
        valid_confirm_request,
        mock_encode_recovery_token,
    ):
        uow = make_uow_recovery(active_recovery_token=None)

        with pytest.raises(InvalidTokenError):
            await AuthService(uow).confirm_password_recovery(valid_confirm_request)

    async def test_does_not_update_password(
        self,
        make_uow_recovery,
        valid_confirm_request,
        mock_encode_recovery_token,
    ):
        uow = make_uow_recovery(active_recovery_token=None)

        with pytest.raises(InvalidTokenError):
            await AuthService(uow).confirm_password_recovery(valid_confirm_request)

        uow.password_repo.get_by_user_id.assert_not_awaited()

    async def test_does_not_revoke_tokens(
        self,
        make_uow_recovery,
        valid_confirm_request,
        mock_encode_recovery_token,
    ):
        uow = make_uow_recovery(active_recovery_token=None)

        with pytest.raises(InvalidTokenError):
            await AuthService(uow).confirm_password_recovery(valid_confirm_request)

        uow.token_repo.revoke_all_by_user_id.assert_not_awaited()

    async def test_does_not_commit(
        self,
        make_uow_recovery,
        valid_confirm_request,
        mock_encode_recovery_token,
    ):
        uow = make_uow_recovery(active_recovery_token=None)

        with pytest.raises(InvalidTokenError):
            await AuthService(uow).confirm_password_recovery(valid_confirm_request)

        uow.commit.assert_not_awaited()


class TestConfirmPasswordRecoveryTokenState:
    """A consumed link and an expired one must not report the same thing."""

    async def test_used_token_is_reported_as_used(
        self,
        make_uow_recovery,
        make_recovery_token,
        valid_confirm_request,
        mock_encode_recovery_token,
    ):
        uow = make_uow_recovery(active_recovery_token=make_recovery_token(used=True))

        with pytest.raises(RecoveryTokenUsedError):
            await AuthService(uow).confirm_password_recovery(valid_confirm_request)

        uow.password_recovery_repo.mark_used.assert_not_awaited()

    async def test_expired_token_is_reported_as_expired(
        self,
        make_uow_recovery,
        make_recovery_token,
        valid_confirm_request,
        mock_encode_recovery_token,
    ):
        uow = make_uow_recovery(
            active_recovery_token=make_recovery_token(expires_in=timedelta(hours=-1))
        )

        with pytest.raises(RecoveryTokenExpiredError):
            await AuthService(uow).confirm_password_recovery(valid_confirm_request)

        uow.commit.assert_not_awaited()


class TestConfirmPasswordRecoveryWithoutStoredPassword:
    """A user with no password row has nothing to reset."""

    async def test_raises_and_leaves_the_token_untouched(
        self,
        make_uow_recovery,
        make_recovery_token,
        valid_confirm_request,
        mock_encode_recovery_token,
    ):
        token = make_recovery_token()
        uow = make_uow_recovery(active_recovery_token=token, password_record=None)

        with pytest.raises(PasswordNotFoundError):
            await AuthService(uow).confirm_password_recovery(valid_confirm_request)

        uow.password_recovery_repo.mark_used.assert_not_awaited()
        uow.token_repo.revoke_all_by_user_id.assert_not_awaited()
        uow.commit.assert_not_awaited()


class TestConfirmPasswordRecoveryDecoupled:
    async def test_field_worker_in_pending_validation_remains_pending(
        self,
        make_uow_recovery,
        make_recovery_token,
        make_password_record,
        make_login_user,
        valid_confirm_request,
        mock_encode_recovery_token,
        mock_hash_password_recovery,
    ):
        user = make_login_user(
            role=UserRole.FIELD_WORKER,
            status=UserStatus.PENDING_VALIDATION,
        )
        user.is_email_verified = False
        token = make_recovery_token(user_id=user.id)
        password_record = make_password_record(user)
        uow = make_uow_recovery(
            active_recovery_token=token,
            password_record=password_record,
            user=user,
        )

        await AuthService(uow).confirm_password_recovery(valid_confirm_request)

        assert password_record.password_hashed == "hashed_newpassword123"
        uow.user_repo.update_email_verification.assert_awaited_once_with(user.id)
        uow.user_repo.update_status.assert_not_awaited()
        uow.password_recovery_repo.mark_used.assert_awaited_once_with(token)
        uow.token_repo.revoke_all_by_user_id.assert_awaited_once_with(user.id)
        uow.commit.assert_awaited_once()


class TestConfirmPasswordRecoveryPendingBackofficeBlocked:
    async def test_pending_admin_is_rejected_with_invalid_recovery_token(
        self,
        make_uow_recovery,
        make_recovery_token,
        make_password_record,
        make_login_user,
        valid_confirm_request,
        mock_encode_recovery_token,
        mock_hash_password_recovery,
    ):
        user = make_login_user(
            role=UserRole.ADMIN,
            status=UserStatus.PENDING_VALIDATION,
        )
        token = make_recovery_token(user_id=user.id)
        uow = make_uow_recovery(
            active_recovery_token=token,
            password_record=make_password_record(user),
            user=user,
        )

        with pytest.raises(InvalidRecoveryTokenError):
            await AuthService(uow).confirm_password_recovery(valid_confirm_request)

        uow.password_repo.get_by_user_id.assert_not_awaited()
        uow.password_recovery_repo.mark_used.assert_not_awaited()
        uow.commit.assert_not_awaited()

    async def test_pending_analyst_is_rejected_with_invalid_recovery_token(
        self,
        make_uow_recovery,
        make_recovery_token,
        make_password_record,
        make_login_user,
        valid_confirm_request,
        mock_encode_recovery_token,
        mock_hash_password_recovery,
    ):
        user = make_login_user(
            role=UserRole.ANALYST,
            status=UserStatus.PENDING_VALIDATION,
        )
        token = make_recovery_token(user_id=user.id)
        uow = make_uow_recovery(
            active_recovery_token=token,
            password_record=make_password_record(user),
            user=user,
        )

        with pytest.raises(InvalidRecoveryTokenError):
            await AuthService(uow).confirm_password_recovery(valid_confirm_request)

        uow.password_repo.get_by_user_id.assert_not_awaited()
        uow.password_recovery_repo.mark_used.assert_not_awaited()
        uow.commit.assert_not_awaited()


class TestRequestPasswordRecoveryPendingBackoffice:
    async def test_pending_admin_skips_recovery_email(
        self,
        make_uow_recovery,
        make_login_user,
        monkeypatch,
    ):
        mock_send_email = AsyncMock()
        monkeypatch.setattr(
            "app.services.auth.auth_service.send_recovery_email",
            mock_send_email,
        )
        user = make_login_user(
            role=UserRole.ADMIN,
            status=UserStatus.PENDING_VALIDATION,
        )
        uow = make_uow_recovery(user=user)

        await AuthService(uow).request_password_recovery(
            PasswordRecoveryRequest(email=user.email)
        )

        uow.password_recovery_repo.revoke_active_for_user.assert_not_awaited()
        uow.password_recovery_repo.create.assert_not_awaited()
        uow.commit.assert_not_awaited()
        mock_send_email.assert_not_awaited()

    async def test_pending_analyst_skips_recovery_email(
        self,
        make_uow_recovery,
        make_login_user,
        monkeypatch,
    ):
        mock_send_email = AsyncMock()
        monkeypatch.setattr(
            "app.services.auth.auth_service.send_recovery_email",
            mock_send_email,
        )
        user = make_login_user(
            role=UserRole.ANALYST,
            status=UserStatus.PENDING_VALIDATION,
        )
        uow = make_uow_recovery(user=user)

        await AuthService(uow).request_password_recovery(
            PasswordRecoveryRequest(email=user.email)
        )

        uow.password_recovery_repo.revoke_active_for_user.assert_not_awaited()
        uow.password_recovery_repo.create.assert_not_awaited()
        uow.commit.assert_not_awaited()
        mock_send_email.assert_not_awaited()

    async def test_active_admin_proceeds_with_recovery(
        self,
        make_uow_recovery,
        make_login_user,
        monkeypatch,
    ):
        mock_send_email = AsyncMock()
        monkeypatch.setattr(
            "app.services.auth.auth_service.send_recovery_email",
            mock_send_email,
        )
        user = make_login_user(
            role=UserRole.ADMIN,
            status=UserStatus.ACTIVE,
        )
        uow = make_uow_recovery(user=user)

        await AuthService(uow).request_password_recovery(
            PasswordRecoveryRequest(email=user.email)
        )

        uow.password_recovery_repo.revoke_active_for_user.assert_awaited_once_with(
            user.id
        )
        uow.password_recovery_repo.create.assert_awaited_once()
        uow.commit.assert_awaited_once()
        mock_send_email.assert_awaited_once()

    async def test_pending_field_worker_proceeds_with_recovery(
        self,
        make_uow_recovery,
        make_login_user,
        monkeypatch,
    ):
        mock_send_email = AsyncMock()
        monkeypatch.setattr(
            "app.services.auth.auth_service.send_recovery_email",
            mock_send_email,
        )
        user = make_login_user(
            role=UserRole.FIELD_WORKER,
            status=UserStatus.PENDING_VALIDATION,
        )
        uow = make_uow_recovery(user=user)

        await AuthService(uow).request_password_recovery(
            PasswordRecoveryRequest(email=user.email)
        )

        uow.password_recovery_repo.revoke_active_for_user.assert_awaited_once_with(
            user.id
        )
        uow.password_recovery_repo.create.assert_awaited_once()
        uow.commit.assert_awaited_once()
        mock_send_email.assert_awaited_once()
