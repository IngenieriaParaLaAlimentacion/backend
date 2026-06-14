import html
import logging
import smtplib
from datetime import datetime
from email.message import EmailMessage
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.core.config import settings

logger = logging.getLogger(__name__)


def build_recovery_deeplink(token: str, user_rol: str = "user") -> str:
    """Build the password recovery deep link, injecting the opaque token."""
    deeplink_url = (
        settings.admin_password_reset_deeplink
        if user_rol in ("admin", "superadmin")
        else settings.password_recovery_deeplink_url
    )
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
        f"  <p>Hi,</p>"
        f"  <p>{pre_button_text}</p>"
        f'  <div style="text-align: center; margin: 30px 0;">'
        f'    <a href="{escaped_url}" style="background-color: {button_color}; '
        f"color: #ffffff; padding: 12px 24px; text-decoration: none; "
        f"border-radius: 5px; font-weight: bold; "
        f'display: inline-block;">{button_text}</a>'
        f"  </div>"
        f'  <p style="font-size: 0.9em; color: #666666;">This link expires on '
        f"<strong>{formatted_expiry}</strong>.</p>"
        f'  <hr style="border: 0; border-top: 1px solid #eeeeee; margin: 20px 0;">'
        f'  <p style="font-size: 0.85em; color: #999999;">'
        f"If you did not request this, you can safely ignore this email.</p>"
        f"</div>"
    )


def _send_email(
    to_email: str,
    subject: str,
    body: str,
    html_body: str,
    log_label: str,
) -> None:
    """Low-level SMTP dispatcher. Not intended for direct use."""
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
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
            if settings.smtp_use_tls:
                smtp.starttls()
            if settings.smtp_username and settings.smtp_password:
                smtp.login(settings.smtp_username, settings.smtp_password)
            smtp.send_message(message)
    except (smtplib.SMTPException, TimeoutError, OSError):
        logger.exception("%s email delivery failed", log_label)


def send_recovery_email(to_email: str, deeplink: str, expires_at: datetime) -> None:
    """Send the password recovery deep link to the user via SMTP."""
    formatted_expiry = expires_at.strftime("%B %d, %Y at %H:%M UTC")

    html_content = _render_base_template(
        title="Reset Your Password",
        pre_button_text=(
            "We received a request to reset your password "
            "for your App account. "
            # TODO: cuando tengamos nombre de app, customizamos
            "Click the button below to proceed:"
        ),
        button_text="Reset Password",
        button_url=deeplink,
        button_color="#007bff",
        formatted_expiry=formatted_expiry,
    )

    _send_email(
        to_email=to_email,
        subject="Password recovery",
        body=(
            "Hi,\n\n"
            "We received a request to reset your password. "
            "Use the following link to continue:\n\n"
            f"{deeplink}\n\n"
            f"This link expires on {formatted_expiry}.\n"
            "If you did not request this, you can ignore this message.\n"
        ),
        html_body=html_content,
        log_label="Password recovery",
    )


def send_invite_email(to_email: str, deeplink: str, expires_at: datetime) -> None:
    """Send an admin invitation email with a password setup link."""
    formatted_expiry = expires_at.strftime("%B %d, %Y at %H:%M UTC")

    html_content = _render_base_template(
        title="Welcome to Ingenieria Para la Alimentacion!",
        pre_button_text=(
            "You have been invited to join"
            " <strong>Ingenieria Para la Alimentacion</strong> "
            "as an administrator. Click the button below to set up "
            "your password and activate your account:"
        ),
        button_text="Set Up Password",
        button_url=deeplink,
        button_color="#28a745",
        formatted_expiry=formatted_expiry,
    )

    _send_email(
        to_email=to_email,
        subject="You've been invited to Ingenieria Para la Alimentacion",
        body=(
            "Hi,\n\n"
            "You have been invited to join Ingenieria Para la Alimentacion "
            "as an administrator. "
            "Use the following link to set up your password:\n\n"
            f"{deeplink}\n\n"
            f"This link expires on {formatted_expiry}.\n"
            "If you were not expecting this invitation, "
            "you can ignore this message.\n"
        ),
        html_body=html_content,
        log_label="Admin invite",
    )
