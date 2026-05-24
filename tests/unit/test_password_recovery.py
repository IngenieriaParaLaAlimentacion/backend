"""Unit tests for build_recovery_deeplink and send_recovery_email."""

import smtplib
from datetime import datetime, timezone
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import pytest

from app.core.config import settings
from app.core.password_recovery import build_recovery_deeplink, send_recovery_email

_FIXED_NOW = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


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
    def test_smtp_disabled_logs_and_skips_send(self, smtp_disabled):
        with patch("app.core.password_recovery.logger") as mock_logger:
            send_recovery_email(
                "user@example.com", "https://app/reset?token=abc", _FIXED_NOW
            )

        mock_logger.info.assert_called_once()

    def test_smtp_disabled_does_not_open_connection(self, smtp_disabled):
        with patch("app.core.password_recovery.smtplib.SMTP") as mock_smtp:
            send_recovery_email(
                "user@example.com", "https://app/reset?token=abc", _FIXED_NOW
            )

        mock_smtp.assert_not_called()

    def test_smtp_enabled_sends_to_correct_recipient(self, smtp_enabled_no_tls):
        with patch("app.core.password_recovery.smtplib.SMTP") as mock_smtp:
            instance = mock_smtp.return_value.__enter__.return_value
            send_recovery_email(
                "user@example.com", "https://app/reset?token=abc", _FIXED_NOW
            )

        instance.send_message.assert_called_once()
        sent_msg = instance.send_message.call_args[0][0]
        assert sent_msg["To"] == "user@example.com"

    def test_smtp_exception_does_not_propagate(self, smtp_enabled_no_tls):
        with patch("app.core.password_recovery.smtplib.SMTP") as mock_smtp:
            mock_smtp.return_value.__enter__.side_effect = smtplib.SMTPException(
                "connection failed"
            )

            # no debe lanzar
            send_recovery_email(
                "user@example.com", "https://app/reset?token=abc", _FIXED_NOW
            )
