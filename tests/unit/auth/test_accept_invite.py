import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.user import UserRole, UserStatus
from app.exceptions.domain_exceptions import (
    InvalidRecoveryTokenError,
    PasswordNotFoundError,
    RecoveryTokenExpiredError,
    RecoveryTokenUsedError,
)
from app.schemas.auth.auth_schema import AcceptInviteRequest
from app.services.auth.auth_service import AuthService


@pytest.fixture
def valid_accept_request():
    return AcceptInviteRequest(
        token="raw_invite_token",
        new_password="newpassword123",
        name="Juana",
        last_name="Perez",
        locality="Palermo",
        description="Bio description",
        contact_phone="+541112345678",
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
def make_uow_invite(make_uow, make_login_user):
    def _make(active_token=None, password_record=None, user=None):
        resolved_user = (
            user
            if user is not None
            else make_login_user(
                role=UserRole.ADMIN, status=UserStatus.PENDING_VALIDATION
            )
        )
        uow = make_uow(password_record=password_record, login_user=resolved_user)
        uow.user_repo.get_by_id = AsyncMock(return_value=resolved_user)
        uow.user_repo.update_profile = AsyncMock()
        uow.user_repo.update_status = AsyncMock()
        uow.user_repo.update_email_verification = AsyncMock()
        uow.password_recovery_repo.get_by_hash = AsyncMock(return_value=active_token)
        uow.password_recovery_repo.mark_used = AsyncMock()
        uow.token_repo.revoke_all_by_user_id = AsyncMock()
        return uow

    return _make


@pytest.fixture
def mock_encode_token(monkeypatch):
    monkeypatch.setattr(
        "app.services.auth.auth_service.hash_token",
        lambda token: "hashed_invite_token",
    )


@pytest.fixture
def mock_hash_password(monkeypatch):
    monkeypatch.setattr(
        "app.services.auth.auth_service.hash_password",
        lambda p: f"hashed_{p}",
    )


class TestAcceptInviteSuccess:
    async def test_accept_invite_by_pending_admin_updates_all_and_activates(
        self,
        make_uow_invite,
        make_recovery_token,
        make_password_record,
        make_login_user,
        valid_accept_request,
        mock_encode_token,
        mock_hash_password,
    ):
        user = make_login_user(
            role=UserRole.ADMIN,
            status=UserStatus.PENDING_VALIDATION,
        )
        token = make_recovery_token(user_id=user.id)
        password_record = make_password_record(user)
        uow = make_uow_invite(
            active_token=token,
            password_record=password_record,
            user=user,
        )

        await AuthService(uow).accept_invite(valid_accept_request)

        uow.password_recovery_repo.get_by_hash.assert_awaited_once_with(
            "hashed_invite_token"
        )
        assert password_record.password_hashed == "hashed_newpassword123"
        uow.user_repo.update_profile.assert_awaited_once_with(
            user.id,
            {
                "name": "Juana",
                "last_name": "Perez",
                "locality": "Palermo",
                "description": "Bio description",
                "contact_phone": "+541112345678",
            },
        )
        uow.user_repo.update_status.assert_awaited_once_with(user.id, UserStatus.ACTIVE)
        uow.user_repo.update_email_verification.assert_awaited_once_with(user.id)
        uow.password_recovery_repo.mark_used.assert_awaited_once_with(token)
        uow.token_repo.revoke_all_by_user_id.assert_awaited_once_with(user.id)
        uow.commit.assert_awaited_once()

    async def test_accept_invite_by_pending_analyst_updates_all_and_activates(
        self,
        make_uow_invite,
        make_recovery_token,
        make_password_record,
        make_login_user,
        valid_accept_request,
        mock_encode_token,
        mock_hash_password,
    ):
        user = make_login_user(
            role=UserRole.ANALYST,
            status=UserStatus.PENDING_VALIDATION,
        )
        token = make_recovery_token(user_id=user.id)
        password_record = make_password_record(user)
        uow = make_uow_invite(
            active_token=token,
            password_record=password_record,
            user=user,
        )

        await AuthService(uow).accept_invite(valid_accept_request)

        assert password_record.password_hashed == "hashed_newpassword123"
        uow.user_repo.update_status.assert_awaited_once_with(user.id, UserStatus.ACTIVE)
        uow.user_repo.update_email_verification.assert_awaited_once_with(user.id)
        uow.password_recovery_repo.mark_used.assert_awaited_once_with(token)
        uow.token_repo.revoke_all_by_user_id.assert_awaited_once_with(user.id)
        uow.commit.assert_awaited_once()

    async def test_accept_invite_with_none_optional_fields(
        self,
        make_uow_invite,
        make_recovery_token,
        make_password_record,
        make_login_user,
        mock_encode_token,
        mock_hash_password,
    ):
        user = make_login_user(
            role=UserRole.ADMIN,
            status=UserStatus.PENDING_VALIDATION,
        )
        token = make_recovery_token(user_id=user.id)
        password_record = make_password_record(user)
        uow = make_uow_invite(
            active_token=token,
            password_record=password_record,
            user=user,
        )

        request = AcceptInviteRequest(
            token="raw_invite_token",
            new_password="newpassword123",
            name="Juana",
            last_name="Perez",
        )
        await AuthService(uow).accept_invite(request)

        uow.user_repo.update_profile.assert_awaited_once_with(
            user.id,
            {
                "name": "Juana",
                "last_name": "Perez",
                "locality": None,
                "description": None,
                "contact_phone": None,
            },
        )
        uow.user_repo.update_status.assert_awaited_once_with(user.id, UserStatus.ACTIVE)


class TestAcceptInviteTokenValidation:
    async def test_unknown_token_raises_invalid_recovery_token(
        self,
        make_uow_invite,
        valid_accept_request,
        mock_encode_token,
    ):
        uow = make_uow_invite(active_token=None)

        with pytest.raises(InvalidRecoveryTokenError):
            await AuthService(uow).accept_invite(valid_accept_request)

        uow.user_repo.update_status.assert_not_awaited()
        uow.commit.assert_not_awaited()

    async def test_used_token_raises_recovery_token_used(
        self,
        make_uow_invite,
        make_recovery_token,
        valid_accept_request,
        mock_encode_token,
    ):
        token = make_recovery_token(used=True)
        uow = make_uow_invite(active_token=token)

        with pytest.raises(RecoveryTokenUsedError):
            await AuthService(uow).accept_invite(valid_accept_request)

        uow.user_repo.update_status.assert_not_awaited()
        uow.commit.assert_not_awaited()

    async def test_expired_token_raises_recovery_token_expired(
        self,
        make_uow_invite,
        make_recovery_token,
        valid_accept_request,
        mock_encode_token,
    ):
        token = make_recovery_token(expires_in=timedelta(hours=-1))
        uow = make_uow_invite(active_token=token)

        with pytest.raises(RecoveryTokenExpiredError):
            await AuthService(uow).accept_invite(valid_accept_request)

        uow.user_repo.update_status.assert_not_awaited()
        uow.commit.assert_not_awaited()


class TestAcceptInviteRoleAndStatusValidation:
    async def test_field_worker_raises_invalid_recovery_token(
        self,
        make_uow_invite,
        make_recovery_token,
        make_login_user,
        valid_accept_request,
        mock_encode_token,
    ):
        user = make_login_user(
            role=UserRole.FIELD_WORKER,
            status=UserStatus.PENDING_VALIDATION,
        )
        token = make_recovery_token(user_id=user.id)
        uow = make_uow_invite(active_token=token, user=user)

        with pytest.raises(InvalidRecoveryTokenError):
            await AuthService(uow).accept_invite(valid_accept_request)

        uow.user_repo.update_status.assert_not_awaited()
        uow.commit.assert_not_awaited()

    async def test_active_admin_raises_invalid_recovery_token(
        self,
        make_uow_invite,
        make_recovery_token,
        make_login_user,
        valid_accept_request,
        mock_encode_token,
    ):
        user = make_login_user(
            role=UserRole.ADMIN,
            status=UserStatus.ACTIVE,
        )
        token = make_recovery_token(user_id=user.id)
        uow = make_uow_invite(active_token=token, user=user)

        with pytest.raises(InvalidRecoveryTokenError):
            await AuthService(uow).accept_invite(valid_accept_request)

        uow.user_repo.update_status.assert_not_awaited()
        uow.commit.assert_not_awaited()

    async def test_active_analyst_raises_invalid_recovery_token(
        self,
        make_uow_invite,
        make_recovery_token,
        make_login_user,
        valid_accept_request,
        mock_encode_token,
    ):
        user = make_login_user(
            role=UserRole.ANALYST,
            status=UserStatus.ACTIVE,
        )
        token = make_recovery_token(user_id=user.id)
        uow = make_uow_invite(active_token=token, user=user)

        with pytest.raises(InvalidRecoveryTokenError):
            await AuthService(uow).accept_invite(valid_accept_request)

        uow.user_repo.update_status.assert_not_awaited()
        uow.commit.assert_not_awaited()

    async def test_user_not_found_raises_invalid_recovery_token(
        self,
        make_uow_invite,
        make_recovery_token,
        valid_accept_request,
        mock_encode_token,
    ):
        token = make_recovery_token()
        uow = make_uow_invite(active_token=token)
        uow.user_repo.get_by_id = AsyncMock(return_value=None)

        with pytest.raises(InvalidRecoveryTokenError):
            await AuthService(uow).accept_invite(valid_accept_request)

        uow.user_repo.update_status.assert_not_awaited()
        uow.commit.assert_not_awaited()

    async def test_user_without_password_record_raises(
        self,
        make_uow_invite,
        make_recovery_token,
        make_login_user,
        valid_accept_request,
        mock_encode_token,
    ):
        user = make_login_user(
            role=UserRole.ADMIN,
            status=UserStatus.PENDING_VALIDATION,
        )
        token = make_recovery_token(user_id=user.id)
        uow = make_uow_invite(active_token=token, password_record=None, user=user)

        with pytest.raises(PasswordNotFoundError):
            await AuthService(uow).accept_invite(valid_accept_request)

        uow.user_repo.update_status.assert_not_awaited()
        uow.commit.assert_not_awaited()
