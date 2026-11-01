"""Current-age and elapsed-time formatting for the subject listing export."""

from datetime import date, datetime, timezone

from app.services.exporters.csv.formatters import format_age
from app.utils.dates import ARGENTINA_TZ, completed_months_between

EMPTY_VALUE = ""


def format_current_age(birth_date: date | None, reference: datetime) -> str:
    """Render current age in completed months as ``18a 6m`` or ``2a 0m``."""
    if birth_date is None:
        return EMPTY_VALUE
    months = completed_months_between(
        birth_date, reference.astimezone(ARGENTINA_TZ).date()
    )
    return format_age(months)


def format_measurement_elapsed(
    measured_at: datetime | None, reference: datetime
) -> str:
    """Render elapsed Argentine calendar time, leaving absent/future days blank."""
    if measured_at is None:
        return EMPTY_VALUE
    if measured_at.tzinfo is None:
        measured_at = measured_at.replace(tzinfo=timezone.utc)
    local_reference = reference.astimezone(ARGENTINA_TZ)
    measured_day = measured_at.astimezone(ARGENTINA_TZ).date()
    days = (local_reference.date() - measured_day).days
    if days < 0:
        return EMPTY_VALUE
    if days == 0:
        return "hoy"
    months = completed_months_between(measured_day, local_reference.date())
    if months >= 12:
        years = months // 12
        return f"hace {years} {'año' if years == 1 else 'años'}"
    if months >= 1:
        return f"hace {months} {'mes' if months == 1 else 'meses'}"
    return f"hace {days} {'día' if days == 1 else 'días'}"
