import html
import logging
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import aiosmtplib
from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from app.config.log_masking import mask_email
from app.config.settings import settings
from app.domain.user import UserRole
from app.exceptions.domain_exceptions import EmailDeliveryError
from app.utils.dates import ARGENTINA_TZ

logger = logging.getLogger(__name__)

_ROLE_LABELS = {
    UserRole.SUPERADMIN: "superadministrador",
    UserRole.ADMIN: "administrador",
    UserRole.ANALYST: "analista",
    UserRole.FIELD_WORKER: "relevador",
}

_ROLE_DESCRIPTIONS = {
    UserRole.SUPERADMIN: "Gestioná todo el panel, incluidos los administradores.",
    UserRole.ADMIN: (
        "Gestioná usuarios, establecimientos, encuestas y solicitudes de acceso."
    ),
    UserRole.ANALYST: (
        "Consultá mediciones, encuestas y tableros de los establecimientos."
    ),
}

_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent.parent / "templates" / "emails"),
    autoescape=select_autoescape(["html"]),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)
# Raíz palette; hex values mirror the backoffice's app/globals.css.
_env.globals["c"] = {
    "papel": "#F6F4EC",
    "papel_atenuado": "#C7CBB8",
    "tinta": "#26251F",
    "tinta_suave": "#6B6759",
    "card": "#FFFFFF",
    "banda": "#F1EFE4",
    "linea": "#DED9C8",
    "tierra": "#26362A",
    "mostaza": "#C99A2E",
    "mostaza_oscura": "#8A6614",
    "mostaza_clara": "#F7EAD0",
    "mostaza_borde": "#E6D1A3",
    "salvia_profunda": "#4E6339",
    "salvia_palida": "#E6EBDC",
    "salvia_borde": "#C9D3B8",
    "ladrillo": "#A9432E",
    "ladrillo_claro": "#F1E1DA",
    "ladrillo_borde": "#DFBFB3",
}
# Gmail drops web fonts, so every stack ends in a font mail clients ship.
_env.globals["f"] = {
    "display": "'Fraunces', Georgia, 'Times New Roman', serif",
    "body": "'Work Sans', Arial, Helvetica, sans-serif",
    "mono": "'IBM Plex Mono', 'Courier New', monospace",
}


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
    """Build the invitation deep link, injecting the opaque token."""
    return _build_deeplink(settings.invite_deeplink_url(user_role), token)


def _render_base_template(
    title: str,
    content_html: str,
    button_text: str | None = None,
    button_url: str | None = None,
    button_color: str | None = None,
    formatted_expiry: str | None = None,
) -> str:
    """Private helper to unify the visual design of all system emails.

    ``content_html`` is the message-specific HTML after the greeting;
    callers wrap it in their own ``<p>``/``<ul>``/etc. tags. The button and
    the expiry note are only rendered when given, so plain notifications
    with no call-to-action link can reuse the same shell.
    """
    button_html = ""
    if button_text and button_url and button_color:
        escaped_url = html.escape(button_url)
        button_html = (
            f'<div style="text-align: center; margin: 30px 0;">'
            f'<a href="{escaped_url}" style="background-color: {button_color}; '
            f"color: #ffffff; padding: 12px 24px; text-decoration: none; "
            f"border-radius: 5px; font-weight: bold; "
            f'display: inline-block;">{button_text}</a>'
            f"</div>"
        )

    expiry_html = ""
    if formatted_expiry:
        expiry_html = (
            f'<p style="font-size: 0.9em; color: #666666;">Este enlace expira el '
            f"<strong>{formatted_expiry}</strong>.</p>"
        )

    return (
        f'<div style="font-family: Arial, sans-serif; max-width: 550px; '
        f'margin: 0 auto; padding: 20px; color: #333333; line-height: 1.6;">'
        f'  <h2 style="color: #111111; margin-bottom: 20px;">{title}</h2>'
        f"  <p>Hola,</p>"
        f"  {content_html}"
        f"  {button_html}"
        f"  {expiry_html}"
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
            mask_email(to_email),
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


def _format_expiry(expires_at: datetime) -> str:
    """Format an expiry instant as ``dd/mm/aaaa, HH:MM`` in Argentina time."""
    return expires_at.astimezone(ARGENTINA_TZ).strftime("%d/%m/%Y, %H:%M")


async def _send_templated(
    to_email: str,
    template: str,
    subject: str,
    log_label: str,
    raise_on_failure: bool = False,
    **context,
) -> None:
    """Render the HTML and plain-text versions of ``template`` from the same
    context and send them."""
    context = {"logo_url": settings.email_logo_url, **context}
    await _send_email(
        to_email=to_email,
        subject=subject,
        body=_env.get_template(f"{template}.txt").render(context),
        html_body=_env.get_template(f"{template}.html").render(context),
        log_label=log_label,
        raise_on_failure=raise_on_failure,
    )


async def send_recovery_email(
    to_email: str, deeplink: str, expires_at: datetime, name: str | None = None
) -> None:
    """Send the password recovery deep link to the user via SMTP."""
    await _send_templated(
        to_email,
        "recovery",
        subject="Restablecé tu contraseña de Raíz",
        log_label="Password recovery",
        name=name,
        account_email=to_email,
        url=deeplink,
        expires_at=_format_expiry(expires_at),
        valid_minutes=settings.password_recovery_token_expire_minutes,
    )


async def send_access_granted_email(
    to_email: str, establishment_names: list[str]
) -> None:
    """Notify a field worker that their establishment access was approved."""
    names = ", ".join(establishment_names)
    html_content = _render_base_template(
        title="Acceso concedido a establecimientos",
        content_html=(
            "<p>Tu solicitud de acceso a los siguientes establecimientos ha "
            "sido aprobada:</p>"
            f"<ul><li>{'</li><li>'.join(establishment_names)}</li></ul>"
            "<p>Ya puedes iniciar sesión y comenzar a trabajar.</p>"
        ),
    )
    await _send_email(
        to_email=to_email,
        subject="Acceso concedido a establecimientos",
        body=(
            "Hola,\n\n"
            "Tu solicitud de acceso a los siguientes establecimientos ha sido "
            f"aprobada:\n\n{names}\n\n"
            "Ya puedes iniciar sesión y comenzar a trabajar."
        ),
        html_body=html_content,
        log_label="Access granted",
    )


async def send_role_changed_email(
    to_email: str, old_role: UserRole, new_role: UserRole
) -> None:
    """Notify a user that an admin changed their role."""
    old_label = _ROLE_LABELS.get(old_role, "usuario")
    new_label = _ROLE_LABELS.get(new_role, "usuario")
    html_content = _render_base_template(
        title="Tu rol fue actualizado",
        content_html=(
            f"<p>Tu rol en <strong>Ingeniería Para la Alimentación</strong> "
            f"cambió de <strong>{old_label}</strong> a "
            f"<strong>{new_label}</strong>.</p>"
            "<p>Por seguridad cerramos tus sesiones abiertas: vuelve a iniciar "
            "sesión para continuar con tu nuevo rol.</p>"
        ),
    )
    await _send_email(
        to_email=to_email,
        subject="Tu rol fue actualizado",
        body=(
            "Hola,\n\n"
            "Tu rol en Ingeniería Para la Alimentación cambió de "
            f"{old_label} a {new_label}.\n\n"
            "Por seguridad cerramos tus sesiones abiertas: vuelve a iniciar "
            "sesión para continuar con tu nuevo rol."
        ),
        html_body=html_content,
        log_label="Role changed",
    )


async def send_creation_denied_email(
    to_email: str, establishment_name: str, reason: str | None = None
) -> None:
    """Notify a field worker that their establishment creation request was denied."""
    reason_text = f"\n\nMotivo: {reason}" if reason else ""
    reason_html = f"<p>Motivo: {reason}</p>" if reason else ""
    html_content = _render_base_template(
        title="Creación de establecimiento denegada",
        content_html=(
            "<p>Tu solicitud de creación del siguiente establecimiento ha "
            "sido denegada:</p>"
            f"<p>{establishment_name}</p>"
            f"{reason_html}"
        ),
    )
    await _send_email(
        to_email=to_email,
        subject="Creación de establecimientos denegada",
        body=(
            "Hola,\n\n"
            "Tu solicitud de creación del siguiente establecimiento ha sido "
            f"denegada:\n\n{establishment_name}.{reason_text}"
        ),
        html_body=html_content,
        log_label="Creation denied",
    )


def build_verification_deeplink(token: str) -> str:
    """Build the email verification deep link, injecting the opaque token."""
    return _build_deeplink(settings.email_verification_deeplink_url, token)


async def send_verification_email(
    to_email: str, deeplink: str, expires_at: datetime, name: str | None = None
) -> None:
    """Send the email verification deep link to the user via SMTP."""
    await _send_templated(
        to_email,
        "verification",
        subject="Confirmá tu correo para Raíz",
        log_label="Email verification",
        name=name,
        url=deeplink,
        expires_at=_format_expiry(expires_at),
    )


async def send_invite_email(
    to_email: str,
    deeplink: str,
    expires_at: datetime,
    role: UserRole = UserRole.ADMIN,
    name: str | None = None,
) -> None:
    """Send a backoffice invitation email with an account activation link."""
    await _send_templated(
        to_email,
        "invite",
        subject="Te invitaron a Raíz",
        log_label="Admin invite",
        raise_on_failure=True,
        name=name,
        role_label=_ROLE_LABELS[role],
        role_description=_ROLE_DESCRIPTIONS[role],
        url=deeplink,
        expires_at=_format_expiry(expires_at),
    )


async def send_establishment_created_email(
    to_email: str, establishment_name: str
) -> None:
    """Notify a field worker that their establishment creation request was
    approved, and access is now pending an admin's review."""
    html_content = _render_base_template(
        title="Establecimiento creado",
        content_html=(
            "<p>Tu solicitud de creación del siguiente establecimiento ha "
            "sido aprobada:</p>"
            f"<p>{establishment_name}</p>"
            "<p>Tu acceso está pendiente de revisión por un administrador. "
            "Te notificaremos cuando sea aprobado.</p>"
        ),
    )
    await _send_email(
        to_email=to_email,
        subject="Establecimiento creado",
        body=(
            "Hola,\n\n"
            "Tu solicitud de creación del siguiente establecimiento ha sido "
            f"aprobada:\n\n{establishment_name}\n\n"
            "Tu acceso está pendiente de revisión por un administrador."
        ),
        html_body=html_content,
        log_label="Establishment created",
    )
