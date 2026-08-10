import html
import logging
from datetime import datetime
from email.message import EmailMessage
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import aiosmtplib

from app.core.config import settings
from app.domain.user import BACKOFFICE_ROLES, UserRole
from app.exceptions.domain_exceptions import EmailDeliveryError

logger = logging.getLogger(__name__)


def _build_deeplink(deeplink_url: str, token: str) -> str:
    """Inject the opaque token as a query param into a deep link URL."""
    parsed = urlsplit(deeplink_url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["token"] = token

    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            urlencode(query),
            parsed.fragment,
        )
    )


def build_recovery_deeplink(token: str) -> str:
    """Build the password recovery deep link, injecting the opaque token.

    Every role is sent to the backoffice origin.
    """
    return _build_deeplink(settings.backoffice_password_reset_deeplink, token)


def build_invite_deeplink(token: str, user_role: UserRole) -> str:
    """Build the invitation deep link, injecting the opaque token.
    Invalid `user_role` values raise a ValueError.
    """
    if user_role not in BACKOFFICE_ROLES:
        raise ValueError("Invalid user role")
    return _build_deeplink(settings.invite_deeplink_url(user_role), token)


def _render_base_template(
    title: str,
    pre_button_text: str,
    button_text: str,
    button_url: str,
    button_color: str,
    formatted_expiry: str,
) -> str:
    """Private helper to unify the visual design of all system emails."""
    escaped_url = html.escape(button_url)

    return (
        f'<div style="font-family: Arial, sans-serif; max-width: 550px; '
        f'margin: 0 auto; padding: 20px; color: #333333; line-height: 1.6;">'
        f'  <h2 style="color: #111111; margin-bottom: 20px;">{title}</h2>'
        f"  <p>Hola,</p>"
        f"  <p>{pre_button_text}</p>"
        f'  <div style="text-align: center; margin: 30px 0;">'
        f'    <a href="{escaped_url}" style="background-color: {button_color}; '
        f"color: #ffffff; padding: 12px 24px; text-decoration: none; "
        f"border-radius: 5px; font-weight: bold; "
        f'display: inline-block;">{button_text}</a>'
        f"  </div>"
        f'  <p style="font-size: 0.9em; color: #666666;">Este enlace expira el '
        f"<strong>{formatted_expiry}</strong>.</p>"
        f'  <hr style="border: 0; border-top: 1px solid #eeeeee; margin: 20px 0;">'
        f'  <p style="font-size: 0.85em; color: #999999;">'
        f"Si no solicitaste esto, puedes ignorar este correo de forma segura.</p>"
        f"</div>"
    )


async def _send_email(
    to_email: str,
    subject: str,
    body: str,
    html_body: str,
    log_label: str,
    raise_on_failure: bool = False,
) -> None:
    """Low-level SMTP dispatcher. Not intended for direct use.

    When ``raise_on_failure`` is True a delivery error is re-raised as
    ``EmailDeliveryError`` so the caller can surface it (e.g. invitations,
    where the recipient must receive the email). Otherwise failures are
    logged and swallowed (fire-and-forget notifications).
    """
    if not settings.smtp_enabled:
        logger.info(
            "%s email skipped because SMTP is disabled: to=%s",
            log_label,
            to_email,
        )
        return

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.smtp_sender_email
    message["To"] = to_email
    message.set_content(body)
    message.add_alternative(html_body, subtype="html")

    try:
        await aiosmtplib.send(
            message,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            start_tls=settings.smtp_use_tls,
            username=settings.smtp_username or None,
            password=settings.smtp_password or None,
            timeout=10,
        )
    except (aiosmtplib.SMTPException, TimeoutError, OSError) as exc:
        logger.exception("%s email delivery failed", log_label)
        if raise_on_failure:
            raise EmailDeliveryError() from exc


async def send_recovery_email(
    to_email: str, deeplink: str, expires_at: datetime
) -> None:
    """Send the password recovery deep link to the user via SMTP."""
    formatted_expiry = expires_at.strftime("%d/%m/%Y a las %H:%M UTC")

    html_content = _render_base_template(
        title="Restablece tu contraseña",
        pre_button_text=(
            "Hemos recibido una solicitud para restablecer la contraseña "
            "de tu cuenta. "
            # TODO: cuando tengamos nombre de app, customizamos
            "Haz clic en el botón de abajo para continuar:"
        ),
        button_text="Restablecer Contraseña",
        button_url=deeplink,
        button_color="#007bff",
        formatted_expiry=formatted_expiry,
    )

    await _send_email(
        to_email=to_email,
        subject="Recuperación de contraseña",
        body=(
            "Hola,\n\n"
            "Hemos recibido una solicitud para restablecer tu contraseña. "
            "Usa el siguiente enlace para continuar:\n\n"
            f"{deeplink}\n\n"
            f"Este enlace expira el {formatted_expiry}.\n"
            "Si no solicitaste esto, puedes ignorar este mensaje.\n"
        ),
        html_body=html_content,
        log_label="Password recovery",
    )


async def send_access_granted_email(
    to_email: str, establishment_names: list[str]
) -> None:
    """Notify a field worker that their establishment access was approved."""
    names = ", ".join(establishment_names)
    await _send_email(
        to_email=to_email,
        subject="Acceso concedido a establecimientos",
        body=(
            "Hola,\n\n"
            "Tu solicitud de acceso a los siguientes establecimientos ha sido "
            f"aprobada:\n\n{names}\n\n"
            "Ya puedes iniciar sesión y comenzar a trabajar."
        ),
        html_body=(
            f"<p>Tu solicitud de acceso a los siguientes establecimientos "
            f"ha sido aprobada:</p>"
            f"<ul><li>{'</li><li>'.join(establishment_names)}</li></ul>"
            f"<p>Ya puedes iniciar sesión y comenzar a trabajar.</p>"
        ),
        log_label="Access granted",
    )


def build_verification_deeplink(token: str) -> str:
    """Build the email verification deep link, injecting the opaque token."""
    return _build_deeplink(settings.email_verification_deeplink_url, token)


async def send_verification_email(
    to_email: str, deeplink: str, expires_at: datetime
) -> None:
    """Send the email verification deep link to the user via SMTP."""
    formatted_expiry = expires_at.strftime("%d/%m/%Y a las %H:%M UTC")

    html_content = _render_base_template(
        title="Verifica tu correo electrónico",
        pre_button_text=(
            "Gracias por registrarte. Por favor verifica tu dirección de correo "
            "electrónico haciendo clic en el botón de abajo para activar tu cuenta:"
        ),
        button_text="Verificar Correo",
        button_url=deeplink,
        button_color="#28a745",
        formatted_expiry=formatted_expiry,
    )

    await _send_email(
        to_email=to_email,
        subject="Verifica tu correo electrónico",
        body=(
            "Hola,\n\n"
            "Gracias por registrarte. Por favor verifica tu dirección de correo "
            "electrónico usando el siguiente enlace:\n\n"
            f"{deeplink}\n\n"
            f"Este enlace expira el {formatted_expiry}.\n"
            "Si no creaste una cuenta, puedes ignorar este mensaje.\n"
        ),
        html_body=html_content,
        log_label="Email verification",
    )


async def send_invite_email(
    to_email: str, deeplink: str, expires_at: datetime, role: str = "admin"
) -> None:
    """Send an admin invitation email with a password setup link."""
    formatted_expiry = expires_at.strftime("%d/%m/%Y a las %H:%M UTC")

    role_label = {
        "admin": "administrador",
        "analyst": "analista",
    }.get(role, "usuario")

    html_content = _render_base_template(
        title="¡Bienvenido a Ingeniería Para la Alimentación!",
        pre_button_text=(
            f"Has sido invitado a unirte a"
            f" <strong>Ingeniería Para la Alimentación</strong> "
            f"como {role_label}. Haz clic en el botón de abajo para configurar "
            f"tu contraseña y activar tu cuenta:"
        ),
        button_text="Configurar Contraseña",
        button_url=deeplink,
        button_color="#28a745",
        formatted_expiry=formatted_expiry,
    )

    await _send_email(
        to_email=to_email,
        subject="Has sido invitado a Ingeniería Para la Alimentación",
        body=(
            "Hola,\n\n"
            "Has sido invitado a unirte a Ingeniería Para la Alimentación. "
            "Usa el siguiente enlace para configurar tu contraseña:\n\n"
            f"{deeplink}\n\n"
            f"Este enlace expira el {formatted_expiry}.\n"
            "Si no esperabas esta invitación, "
            "puedes ignorar este mensaje.\n"
        ),
        html_body=html_content,
        log_label="Admin invite",
        raise_on_failure=True,
    )
