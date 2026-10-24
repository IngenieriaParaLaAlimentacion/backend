from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlparse

import aiosmtplib
import pytest

from app.config.settings import settings
from app.domain.user import UserRole
from app.exceptions.domain_exceptions import EmailDeliveryError
from app.services.email_service import (
    build_invite_deeplink,
    build_recovery_deeplink,
    send_access_granted_email,
    send_creation_denied_email,
    send_establishment_created_email,
    send_invite_email,
    send_recovery_email,
    send_role_changed_email,
    send_verification_email,
)

_FIXED_NOW = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


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
    @pytest.mark.parametrize("role", [UserRole.ADMIN, UserRole.ANALYST])
    def test_role_selects_its_backoffice_invite_path(
        self, invite_deeplink_settings, role
    ):
        result = build_invite_deeplink("tok123", user_role=role)
        assert (
            result == f"https://backoffice.example.com/invite/{role.value}?token=tok123"
        )

    def test_trailing_slash_in_base_does_not_duplicate(self, monkeypatch):
        monkeypatch.setattr(
            settings, "backoffice_deeplink_base", "https://backoffice.example.com/"
        )
        monkeypatch.setattr(settings, "invite_path", "/invite")

        result = build_invite_deeplink("tok123", user_role=UserRole.ANALYST)
        assert urlparse(result).path == "/invite/analyst"


class TestSendRecoveryEmail:
    async def test_smtp_disabled_logs_and_skips_send(self, smtp_disabled):
        with (
            patch("app.services.email_service.logger") as mock_logger,
            patch(
                "app.services.email_service.aiosmtplib.send", new_callable=AsyncMock
            ) as mock_send,
        ):
            await send_recovery_email(
                "user@example.com", "https://app/reset?token=abc", _FIXED_NOW
            )

        mock_logger.info.assert_called_once()
        mock_send.assert_not_called()

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
    async def test_smtp_disabled_logs_and_skips_send(self, smtp_disabled):
        with (
            patch("app.services.email_service.logger") as mock_logger,
            patch(
                "app.services.email_service.aiosmtplib.send", new_callable=AsyncMock
            ) as mock_send,
        ):
            await send_access_granted_email("worker@test.com", ["Centro A", "Centro B"])

        mock_logger.info.assert_called_once()
        mock_send.assert_not_called()

    async def test_smtp_enabled_sends_to_correct_recipient(self, smtp_enabled_no_tls):
        with patch(
            "app.services.email_service.aiosmtplib.send", new_callable=AsyncMock
        ) as mock_send:
            await send_access_granted_email("worker@test.com", ["Centro A", "Centro B"])

        mock_send.assert_awaited_once()
        sent_msg = mock_send.call_args[0][0]
        assert sent_msg["To"] == "worker@test.com"

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

    async def test_smtp_exception_does_not_propagate(self, smtp_enabled_no_tls):
        with patch(
            "app.services.email_service.aiosmtplib.send",
            new_callable=AsyncMock,
            side_effect=aiosmtplib.SMTPException("connection failed"),
        ):
            await send_access_granted_email("worker@test.com", ["Centro A"])


class TestSmtpDisabledLogging:
    async def test_recipient_is_masked_in_the_skip_log(self, smtp_disabled, caplog):
        with caplog.at_level("INFO", logger="app.services.email_service"):
            await send_recovery_email(
                "juana@dominio.com", "https://app/reset?token=abc", _FIXED_NOW
            )

        assert "juana@dominio.com" not in caplog.text
        assert "j***@dominio.com" in caplog.text


class TestSendInviteEmail:
    async def test_smtp_enabled_sends_to_correct_recipient(self, smtp_enabled_no_tls):
        with patch(
            "app.services.email_service.aiosmtplib.send", new_callable=AsyncMock
        ) as mock_send:
            await send_invite_email(
                "invited@test.com", "https://backoffice/set?token=abc", _FIXED_NOW
            )

        mock_send.assert_awaited_once()
        assert mock_send.call_args[0][0]["To"] == "invited@test.com"

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


_EXPIRES_AT = datetime(2024, 6, 1, 15, 7, tzinfo=timezone.utc)
_LINK = "https://backoffice.example.com/path?token=abc"


@pytest.fixture
def sent():
    """Capture the arguments of the single SMTP dispatch made by the test."""
    with patch(
        "app.services.email_service._send_email", new_callable=AsyncMock
    ) as mock_send:
        yield mock_send


def _sent_email(mock_send) -> dict:
    mock_send.assert_awaited_once()
    return mock_send.call_args.kwargs


class TestEmailContent:
    @pytest.mark.parametrize(
        ("send", "subject"),
        [
            (
                lambda: send_invite_email("a@b.c", _LINK, _EXPIRES_AT, UserRole.ADMIN),
                "Te invitaron a Raíz",
            ),
            (
                lambda: send_recovery_email("a@b.c", _LINK, _EXPIRES_AT),
                "Restablecé tu contraseña de Raíz",
            ),
            (
                lambda: send_verification_email("a@b.c", _LINK, _EXPIRES_AT),
                "Confirmá tu correo para Raíz",
            ),
            (
                lambda: send_access_granted_email("a@b.c", ["Centro A"]),
                "Ya tenés acceso a 1 establecimiento",
            ),
            (
                lambda: send_access_granted_email("a@b.c", ["Centro A", "Centro B"]),
                "Ya tenés acceso a 2 establecimientos",
            ),
            (
                lambda: send_role_changed_email(
                    "a@b.c", UserRole.FIELD_WORKER, UserRole.ANALYST
                ),
                "Cambió tu rol en Raíz",
            ),
            (
                lambda: send_establishment_created_email("a@b.c", "Centro A"),
                "Creamos Centro A",
            ),
            (
                lambda: send_creation_denied_email("a@b.c", "Centro A"),
                "No aprobamos la solicitud de Centro A",
            ),
        ],
    )
    async def test_subject(self, sent, send, subject):
        await send()

        assert _sent_email(sent)["subject"] == subject

    @pytest.mark.parametrize(
        "send",
        [
            lambda: send_invite_email("a@b.c", _LINK, _EXPIRES_AT, UserRole.ADMIN),
            lambda: send_recovery_email("a@b.c", _LINK, _EXPIRES_AT),
            lambda: send_verification_email("a@b.c", _LINK, _EXPIRES_AT),
        ],
    )
    async def test_link_and_expiry_in_argentina_time(self, sent, send):
        await send()

        email = _sent_email(sent)
        for part in (email["html_body"], email["body"]):
            assert "01/06/2024, 12:07" in part
            assert "hora de Argentina" in part
        assert _LINK in email["body"]
        assert _LINK in email["html_body"]

    @pytest.mark.parametrize(
        "send",
        [
            lambda name: send_access_granted_email("a@b.c", [name]),
            lambda name: send_establishment_created_email("a@b.c", name),
            lambda name: send_creation_denied_email("a@b.c", "Centro", reason=name),
        ],
    )
    async def test_dynamic_values_are_html_escaped(self, sent, send):
        await send("<b>X</b>")

        email = _sent_email(sent)
        assert "<b>X</b>" not in email["html_body"]
        assert "&lt;b&gt;X&lt;/b&gt;" in email["html_body"]
        assert "<b>X</b>" in email["body"]

    @pytest.mark.parametrize(
        ("name", "greeting"), [("Lucía", "Hola, Lucía:"), (None, "Hola:")]
    )
    async def test_greeting(self, sent, name, greeting):
        await send_recovery_email("a@b.c", _LINK, _EXPIRES_AT, name)

        email = _sent_email(sent)
        assert greeting in email["html_body"]
        assert email["body"].startswith(greeting)

    async def test_invite_shows_role(self, sent):
        await send_invite_email("a@b.c", _LINK, _EXPIRES_AT, UserRole.ANALYST)

        email = _sent_email(sent)
        assert "Analista" in email["html_body"]
        assert "analista" in email["body"]

    @pytest.mark.parametrize(
        ("new_role", "has_button"),
        [
            (UserRole.ADMIN, True),
            (UserRole.ANALYST, True),
            (UserRole.FIELD_WORKER, False),
        ],
    )
    async def test_role_change_signin_button_only_for_backoffice_roles(
        self, sent, monkeypatch, new_role, has_button
    ):
        monkeypatch.setattr(
            settings, "backoffice_deeplink_base", "https://backoffice.example.com"
        )
        old_role = UserRole.ANALYST if new_role != UserRole.ANALYST else UserRole.ADMIN

        await send_role_changed_email("a@b.c", old_role, new_role)

        email = _sent_email(sent)
        signin_url = "https://backoffice.example.com/signin"
        assert (signin_url in email["html_body"]) is has_button
        assert (signin_url in email["body"]) is has_button

    @pytest.mark.parametrize(
        ("reason", "expected"),
        [
            ("Datos incompletos", "Datos incompletos"),
            (None, "El administrador no indicó un motivo."),
        ],
    )
    async def test_creation_denied_reason(self, sent, reason, expected):
        await send_creation_denied_email("a@b.c", "Centro A", reason)

        email = _sent_email(sent)
        assert expected in email["html_body"]
        assert expected in email["body"]
