import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import parse_qs, urlparse

import aiosmtplib
import pytest

from app.core.config import settings
from app.core.password_recovery import build_recovery_deeplink, send_recovery_email
from app.exceptions.domain_exceptions import InvalidTokenError
from app.schemas.auth_schema import PasswordRecoveryConfirmRequest
from app.services.auth_service import AuthService

_FIXED_NOW = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


# ── Deeplink fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def user_deeplink_settings(monkeypatch):
    monkeypatch.setattr(settings, "app_deeplink_base", "https://app.example.com")
    monkeypatch.setattr(settings, "password_recovery_path", "/reset-password")


@pytest.fixture
def admin_deeplink_settings(monkeypatch):
    monkeypatch.setattr(
        settings, "backoffice_deeplink_base", "https://backoffice.example.com"
    )
    monkeypatch.setattr(settings, "password_recovery_path", "/reset-password")


@pytest.fixture
def smtp_disabled(monkeypatch):
    monkeypatch.setattr(settings, "smtp_enabled", False)


@pytest.fixture
def smtp_enabled_no_tls(monkeypatch):
    monkeypatch.setattr(settings, "smtp_enabled", True)
    monkeypatch.setattr(settings, "smtp_host", "localhost")
    monkeypatch.setattr(settings, "smtp_port", 1025)
    monkeypatch.setattr(settings, "smtp_use_tls", False)
    monkeypatch.setattr(settings, "smtp_username", None)
    monkeypatch.setattr(settings, "smtp_password", None)


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
        "app.services.auth_service.encode_refresh_token",
        lambda token: "hashed_recovery_token",
    )


@pytest.fixture
def mock_hash_password_recovery(monkeypatch):
    monkeypatch.setattr(
        "app.services.auth_service.hash_password",
        lambda p: f"hashed_{p}",
    )


# ── TestBuildRecoveryDeeplink ────────────────────────────────────────────────


class TestBuildRecoveryDeeplink:
    def test_user_role_uses_user_deeplink(self, user_deeplink_settings):
        result = build_recovery_deeplink("tok123", user_rol="user")
        assert urlparse(result).netloc == "app.example.com"

    def test_admin_role_uses_admin_deeplink(self, admin_deeplink_settings):
        result = build_recovery_deeplink("tok123", user_rol="admin")
        assert urlparse(result).netloc == "backoffice.example.com"

    def test_superadmin_role_uses_admin_deeplink(self, admin_deeplink_settings):
        result = build_recovery_deeplink("tok123", user_rol="superadmin")
        assert urlparse(result).netloc == "backoffice.example.com"

    def test_unknown_role_falls_back_to_user_deeplink(self, user_deeplink_settings):
        result = build_recovery_deeplink("tok123", user_rol="unknown")
        assert urlparse(result).netloc == "app.example.com"

    def test_default_role_uses_user_deeplink(self, user_deeplink_settings):
        result = build_recovery_deeplink("tok123")
        assert urlparse(result).netloc == "app.example.com"

    def test_token_injected_as_query_param(self, user_deeplink_settings):
        result = build_recovery_deeplink("abc123")
        assert parse_qs(urlparse(result).query)["token"] == ["abc123"]

    def test_token_injected_for_admin(self, admin_deeplink_settings):
        result = build_recovery_deeplink("admin-token", user_rol="admin")
        assert parse_qs(urlparse(result).query)["token"] == ["admin-token"]

    def test_scheme_netloc_path_and_existing_params_preserved(self, monkeypatch):
        monkeypatch.setattr(settings, "app_deeplink_base", "https://foo")
        monkeypatch.setattr(settings, "password_recovery_path", "/reset?x=1")

        result = build_recovery_deeplink("abc123")
        parsed = urlparse(result)
        qs = parse_qs(parsed.query)

        assert parsed.scheme == "https"
        assert parsed.netloc == "foo"
        assert parsed.path == "/reset"
        assert qs["x"] == ["1"]
        assert qs["token"] == ["abc123"]

    def test_token_overwrites_existing_token_param(self, monkeypatch):
        monkeypatch.setattr(settings, "app_deeplink_base", "https://foo")
        monkeypatch.setattr(settings, "password_recovery_path", "/reset?token=old")

        result = build_recovery_deeplink("new-token")
        assert parse_qs(urlparse(result).query)["token"] == ["new-token"]


class TestSendRecoveryEmail:
    @pytest.mark.asyncio
    async def test_smtp_disabled_logs_and_skips_send(self, smtp_disabled):
        with patch("app.core.password_recovery.logger") as mock_logger:
            await send_recovery_email(
                "user@example.com", "https://app/reset?token=abc", _FIXED_NOW
            )

        mock_logger.info.assert_called_once()

    @pytest.mark.asyncio
    async def test_smtp_disabled_does_not_send(self, smtp_disabled):
        with patch(
            "app.core.password_recovery.aiosmtplib.send", new_callable=AsyncMock
        ) as mock_send:
            await send_recovery_email(
                "user@example.com", "https://app/reset?token=abc", _FIXED_NOW
            )

        mock_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_smtp_enabled_sends_to_correct_recipient(self, smtp_enabled_no_tls):
        with patch(
            "app.core.password_recovery.aiosmtplib.send", new_callable=AsyncMock
        ) as mock_send:
            await send_recovery_email(
                "user@example.com", "https://app/reset?token=abc", _FIXED_NOW
            )

        mock_send.assert_awaited_once()
        sent_msg = mock_send.call_args[0][0]  # first positional arg is the EmailMessage
        assert sent_msg["To"] == "user@example.com"

    @pytest.mark.asyncio
    async def test_smtp_exception_does_not_propagate(self, smtp_enabled_no_tls):
        with patch(
            "app.core.password_recovery.aiosmtplib.send",
            new_callable=AsyncMock,
            side_effect=aiosmtplib.SMTPException("connection failed"),
        ):
            await send_recovery_email(
                "user@example.com", "https://app/reset?token=abc", _FIXED_NOW
            )
        # no assert — just verifying no exception escapes


# ── TestConfirmPasswordRecoverySuccess ───────────────────────────────────────


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
