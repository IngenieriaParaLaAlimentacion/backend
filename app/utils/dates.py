from datetime import date, datetime
from zoneinfo import ZoneInfo

# Establishments operate in Argentina; "today" for future-date validation
# is judged against local calendar date, not UTC, to avoid false rejections
# near the day boundary (ART is UTC-3).
ARGENTINA_TZ = ZoneInfo("America/Argentina/Buenos_Aires")


def today_in_argentina() -> date:
    return datetime.now(ARGENTINA_TZ).date()


def is_future_date(v: datetime) -> bool:
    """Compare calendar dates only, tolerant of client clock drift."""
    return v.astimezone(ARGENTINA_TZ).date() > today_in_argentina()
