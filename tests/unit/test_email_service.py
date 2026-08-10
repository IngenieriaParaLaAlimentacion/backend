from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlparse

import aiosmtplib
import pytest

from app.core.config import settings
from app.domain.user import UserRole
from app.exceptions.domain_exceptions import EmailDeliveryError
from app.services.email_service import (
    build_invite_deeplink,
    build_recovery_deeplink,
    send_access_granted_email,
    send_invite_email,
    send_recovery_email,
)

_FIXED_NOW = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def recovery_deeplink_settings(monkeypatch):
    monkeypatch.setattr(
        settings, "backoffice_deeplink_base", "https://backoffice.example.com"
    )
    monkeypatch.setattr(settings, "password_recovery_path", "/reset-password")


@pytest.fixture
def invite_deeplink_settings(monkeypatch):
    monkeypatch.setattr(
        settings, "backoffice_deeplink_base", "https://backoffice.example.com"
    )
    monkeypatch.setattr(settings, "invite_path", "/invite")


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


class TestBuildRecoveryDeeplink:
    def test_uses_backoffice_origin(self, recovery_deeplink_settings):
        result = build_recovery_deeplink("tok123")
        assert urlparse(result).netloc == "backoffice.example.com"

    def test_uses_configured_recovery_path(self, recovery_deeplink_settings):
        result = build_recovery_deeplink("tok123")
        assert urlparse(result).path == "/reset-password"

    def test_token_injected_as_query_param(self, recovery_deeplink_settings):
        result = build_recovery_deeplink("abc123")
        assert parse_qs(urlparse(result).query)["token"] == ["abc123"]

    def test_scheme_netloc_path_and_existing_params_preserved(self, monkeypatch):
        monkeypatch.setattr(settings, "backoffice_deeplink_base", "https://foo")
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
        monkeypatch.setattr(settings, "backoffice_deeplink_base", "https://foo")
        monkeypatch.setattr(settings, "password_recovery_path", "/reset?token=old")

        result = build_recovery_deeplink("new-token")
        assert parse_qs(urlparse(result).query)["token"] == ["new-token"]


class TestBuildInviteDeeplink:
    def test_admin_role_uses_backoffice_invite_admin_path(
        self, invite_deeplink_settings
    ):
        result = build_invite_deeplink("tok123", user_role=UserRole.ADMIN)
        assert result == "https://backoffice.example.com/invite/admin?token=tok123"

    def test_analyst_role_uses_backoffice_invite_analyst_path(
        self, invite_deeplink_settings
    ):
        result = build_invite_deeplink("tok123", user_role=UserRole.ANALYST)
        assert result == "https://backoffice.example.com/invite/analyst?token=tok123"

    def test_enum_role_resolves_to_its_value(self, invite_deeplink_settings):
        result = build_invite_deeplink("tok123", user_role=UserRole.ANALYST)
        assert urlparse(result).path == "/invite/analyst"

    def test_trailing_slash_in_base_does_not_duplicate(self, monkeypatch):
        monkeypatch.setattr(
            settings, "backoffice_deeplink_base", "https://backoffice.example.com/"
        )
        monkeypatch.setattr(settings, "invite_path", "/invite")

        result = build_invite_deeplink("tok123", user_role=UserRole.ANALYST)
        assert urlparse(result).path == "/invite/analyst"


class TestSendRecoveryEmail:
    @pytest.mark.asyncio
    async def test_smtp_disabled_logs_and_skips_send(self, smtp_disabled):
        with patch("app.services.email_service.logger") as mock_logger:
            await send_recovery_email(
                "user@example.com", "https://app/reset?token=abc", _FIXED_NOW
            )

        mock_logger.info.assert_called_once()

    @pytest.mark.asyncio
    async def test_smtp_disabled_does_not_send(self, smtp_disabled):
        with patch(
            "app.services.email_service.aiosmtplib.send", new_callable=AsyncMock
        ) as mock_send:
            await send_recovery_email(
                "user@example.com", "https://app/reset?token=abc", _FIXED_NOW
            )

        mock_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_smtp_enabled_sends_to_correct_recipient(self, smtp_enabled_no_tls):
        with patch(
            "app.services.email_service.aiosmtplib.send", new_callable=AsyncMock
        ) as mock_send:
            await send_recovery_email(
                "user@example.com", "https://app/reset?token=abc", _FIXED_NOW
            )

        mock_send.assert_awaited_once()
        sent_msg = mock_send.call_args[0][0]
        assert sent_msg["To"] == "user@example.com"

    @pytest.mark.asyncio
    async def test_smtp_exception_does_not_propagate(self, smtp_enabled_no_tls):
        with patch(
            "app.services.email_service.aiosmtplib.send",
            new_callable=AsyncMock,
            side_effect=aiosmtplib.SMTPException("connection failed"),
        ):
            await send_recovery_email(
                "user@example.com", "https://app/reset?token=abc", _FIXED_NOW
            )


class TestSendAccessGrantedEmail:
    @pytest.mark.asyncio
    async def test_smtp_disabled_logs_and_skips_send(self, smtp_disabled):
        with patch("app.services.email_service.logger") as mock_logger:
            await send_access_granted_email("worker@test.com", ["Centro A", "Centro B"])

        mock_logger.info.assert_called_once()

    @pytest.mark.asyncio
    async def test_smtp_disabled_does_not_send(self, smtp_disabled):
        with patch(
            "app.services.email_service.aiosmtplib.send", new_callable=AsyncMock
        ) as mock_send:
            await send_access_granted_email("worker@test.com", ["Centro A", "Centro B"])

        mock_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_smtp_enabled_sends_to_correct_recipient(self, smtp_enabled_no_tls):
        with patch(
            "app.services.email_service.aiosmtplib.send", new_callable=AsyncMock
        ) as mock_send:
            await send_access_granted_email("worker@test.com", ["Centro A", "Centro B"])

        mock_send.assert_awaited_once()
        sent_msg = mock_send.call_args[0][0]
        assert sent_msg["To"] == "worker@test.com"

    @pytest.mark.asyncio
    async def test_smtp_enabled_sends_with_subject(self, smtp_enabled_no_tls):
        with patch(
            "app.services.email_service.aiosmtplib.send", new_callable=AsyncMock
        ) as mock_send:
            await send_access_granted_email("worker@test.com", ["Centro A", "Centro B"])

        sent_msg = mock_send.call_args[0][0]
        assert "Acceso concedido" in sent_msg["Subject"]

    @pytest.mark.asyncio
    async def test_includes_establishment_names_in_body(self, smtp_enabled_no_tls):
        with patch(
            "app.services.email_service.aiosmtplib.send", new_callable=AsyncMock
        ) as mock_send:
            await send_access_granted_email("worker@test.com", ["Centro A", "Centro B"])

        sent_msg = mock_send.call_args[0][0]
        text_part = sent_msg.get_payload()[0]
        body = text_part.get_payload(decode=True).decode()
        assert "Centro A" in body
        assert "Centro B" in body

    @pytest.mark.asyncio
    async def test_single_establishment_works(self, smtp_enabled_no_tls):
        with patch(
            "app.services.email_service.aiosmtplib.send", new_callable=AsyncMock
        ) as mock_send:
            await send_access_granted_email("worker@test.com", ["Centro A"])

        mock_send.assert_awaited_once()
        sent_msg = mock_send.call_args[0][0]
        text_part = sent_msg.get_payload()[0]
        body = text_part.get_payload(decode=True).decode()
        assert "Centro A" in body

    @pytest.mark.asyncio
    async def test_smtp_exception_does_not_propagate(self, smtp_enabled_no_tls):
        with patch(
            "app.services.email_service.aiosmtplib.send",
            new_callable=AsyncMock,
            side_effect=aiosmtplib.SMTPException("connection failed"),
        ):
            await send_access_granted_email("worker@test.com", ["Centro A"])


class TestSendInviteEmail:
    @pytest.mark.asyncio
    async def test_smtp_enabled_sends_to_correct_recipient(self, smtp_enabled_no_tls):
        with patch(
            "app.services.email_service.aiosmtplib.send", new_callable=AsyncMock
        ) as mock_send:
            await send_invite_email(
                "invited@test.com", "https://backoffice/set?token=abc", _FIXED_NOW
            )

        mock_send.assert_awaited_once()
        assert mock_send.call_args[0][0]["To"] == "invited@test.com"

    @pytest.mark.asyncio
    async def test_smtp_exception_raises_email_delivery_error(
        self, smtp_enabled_no_tls
    ):
        """Unlike fire-and-forget emails, a failed invite must surface so the
        caller does not report success."""
        with patch(
            "app.services.email_service.aiosmtplib.send",
            new_callable=AsyncMock,
            side_effect=aiosmtplib.SMTPException("connection failed"),
        ):
            with pytest.raises(EmailDeliveryError):
                await send_invite_email(
                    "invited@test.com", "https://backoffice/set?token=abc", _FIXED_NOW
                )
