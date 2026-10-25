"""Render every system email with sample data into HTML files, without SMTP.

Usage: poetry run python -m scripts.preview_emails [out_dir]
Set PUBLIC_BASE_URL to a deployed backend so the logo loads.
"""

import asyncio
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.domain.user import UserRole
from app.services import email_service


async def main(out_dir: Path) -> None:
    """Write one ``<email>.html`` per system email into ``out_dir``."""
    out_dir.mkdir(parents=True, exist_ok=True)

    async def _write(*, html_body: str, log_label: str, **_) -> None:
        path = out_dir / f"{log_label.lower().replace(' ', '_')}.html"
        path.write_text(html_body, encoding="utf-8")
        print(path)

    email_service._send_email = _write

    expires_at = datetime.now(timezone.utc) + timedelta(days=1)
    link = "https://backoffice.raiz.app/path?token=Xk29"
    await email_service.send_invite_email(
        "ana@example.com", link, expires_at, UserRole.ADMIN
    )
    await email_service.send_recovery_email(
        "lucia.perez@gmail.com", link, expires_at, "Lucía"
    )
    await email_service.send_verification_email(
        "martin@example.com", link, expires_at, "Martín"
    )
    await email_service.send_access_granted_email(
        "martin@example.com",
        ["Comedor Los Girasoles", "Merendero Rayito de Sol"],
        "Martín",
    )
    await email_service.send_role_changed_email(
        "martin@example.com", UserRole.FIELD_WORKER, UserRole.ANALYST, "Martín"
    )
    await email_service.send_establishment_created_email(
        "martin@example.com", "Comedor Los Girasoles", "Martín"
    )
    await email_service.send_creation_denied_email(
        "martin@example.com",
        "Comedor Los Girasoles",
        "Ya existe un establecimiento registrado en Av. San Martín 1240.",
        "Martín",
    )


if __name__ == "__main__":
    default_dir = Path(tempfile.gettempdir()) / "raiz_email_previews"
    asyncio.run(main(Path(sys.argv[1]) if len(sys.argv) > 1 else default_dir))
