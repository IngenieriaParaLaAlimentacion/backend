import logging
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import aiosmtplib
from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from app.config.log_masking import mask_email
from app.config.settings import settings
from app.domain.user import BACKOFFICE_ROLES, UserRole
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
    to_email: str, establishment_names: list[str], name: str | None = None
) -> None:
    """Notify a field worker that their establishment access was approved."""
    count = len(establishment_names)
    noun = "establecimiento" if count == 1 else "establecimientos"
    await _send_templated(
        to_email,
        "access_granted",
        subject=f"Ya tenés acceso a {count} {noun}",
        log_label="Access granted",
        name=name,
        establishment_names=establishment_names,
    )


async def send_role_changed_email(
    to_email: str, old_role: UserRole, new_role: UserRole, name: str | None = None
) -> None:
    """Notify a user that an admin changed their role."""
    await _send_templated(
        to_email,
        "role_changed",
        subject="Cambió tu rol en Raíz",
        log_label="Role changed",
        name=name,
        old_role_label=_ROLE_LABELS[old_role],
        new_role_label=_ROLE_LABELS[new_role],
        # Field workers only use the mobile app, which has no sign-in link.
        signin_url=(
            settings.backoffice_signin_url if new_role in BACKOFFICE_ROLES else None
        ),
    )


async def send_creation_denied_email(
    to_email: str,
    establishment_name: str,
    reason: str | None = None,
    name: str | None = None,
) -> None:
    """Notify a field worker that their establishment creation request was denied."""
    await _send_templated(
        to_email,
        "creation_denied",
        subject=f"No aprobamos la solicitud de {establishment_name}",
        log_label="Creation denied",
        name=name,
        establishment_name=establishment_name,
        reason=reason,
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
    to_email: str, establishment_name: str, name: str | None = None
) -> None:
    """Notify a field worker that their establishment creation request was
    approved, and access is now pending an admin's review."""
    await _send_templated(
        to_email,
        "establishment_created",
        subject=f"Creamos {establishment_name}",
        log_label="Establishment created",
        name=name,
        establishment_name=establishment_name,
    )
