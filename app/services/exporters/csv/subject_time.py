"""Current-age and elapsed-time formatting for the subject listing export."""

from datetime import date, datetime, timezone

from app.reference_data.anthropometry import age_in_months
from app.utils.dates import ARGENTINA_TZ

EMPTY_VALUE = ""


def format_current_age(birth_date: date | None, reference: datetime) -> str:
    """Render current age in completed months as ``18 a 6 m``, ``2 a`` or ``3 m``."""
    if birth_date is None:
        return EMPTY_VALUE
    months = age_in_months(birth_date, reference.astimezone(ARGENTINA_TZ))
    # Match web formatAgeMonths while preserving format_age for establishment CSVs.
    years, rest = divmod(months, 12)
    if years == 0:
        return f"{rest} m"
    return f"{years} a" if rest == 0 else f"{years} a {rest} m"


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
    months = age_in_months(measured_day, local_reference)
    if months >= 12:
        years = months // 12
        return f"hace {years} {'año' if years == 1 else 'años'}"
    if months >= 1:
        return f"hace {months} {'mes' if months == 1 else 'meses'}"
    return f"hace {days} {'día' if days == 1 else 'días'}"
