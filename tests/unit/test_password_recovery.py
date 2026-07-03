import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.exceptions.domain_exceptions import InvalidTokenError
from app.schemas.auth_schema import PasswordRecoveryConfirmRequest
from app.services.auth_service import AuthService


@pytest.fixture
def valid_confirm_request():
    return PasswordRecoveryConfirmRequest(
        token="raw_recovery_token",
        new_password="newpassword123",
    )


@pytest.fixture
def make_recovery_token():
    def _make():
        t = MagicMock()
        t.user_id = uuid.uuid4()
        return t

    return _make


@pytest.fixture
def make_uow_recovery(make_uow, make_recovery_token):
    def _make(active_recovery_token=None, password_record=None):
        uow = make_uow(password_record=password_record)
        uow.password_recovery_repo.get_active_token = AsyncMock(
            return_value=active_recovery_token
        )
        uow.password_recovery_repo.mark_used = AsyncMock()
        uow.token_repo.revoke_all_by_user_id = AsyncMock()
        return uow

    return _make


@pytest.fixture
def mock_encode_recovery_token(monkeypatch):
    monkeypatch.setattr(
        "app.services.auth_service.hash_token",
        lambda token: "hashed_recovery_token",
    )


@pytest.fixture
def mock_hash_password_recovery(monkeypatch):
    monkeypatch.setattr(
        "app.services.auth_service.hash_password",
        lambda p: f"hashed_{p}",
    )


class TestConfirmPasswordRecoverySuccess:
    @pytest.mark.asyncio
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

        uow.password_recovery_repo.get_active_token.assert_awaited_once_with(
            "hashed_recovery_token"
        )

    @pytest.mark.asyncio
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

    @pytest.mark.asyncio
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

    @pytest.mark.asyncio
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

    @pytest.mark.asyncio
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
    @pytest.mark.asyncio
    async def test_raises_invalid_token_error(
        self,
        make_uow_recovery,
        valid_confirm_request,
        mock_encode_recovery_token,
    ):
        uow = make_uow_recovery(active_recovery_token=None)

        with pytest.raises(InvalidTokenError):
            await AuthService(uow).confirm_password_recovery(valid_confirm_request)

    @pytest.mark.asyncio
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

    @pytest.mark.asyncio
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

    @pytest.mark.asyncio
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
