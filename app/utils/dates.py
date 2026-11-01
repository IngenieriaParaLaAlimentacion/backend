from datetime import date, datetime
from zoneinfo import ZoneInfo

# Establishments operate in Argentina; "today" for future-date validation
# is judged against local calendar date, not UTC, to avoid false rejections
# near the day boundary (ART is UTC-3).
ARGENTINA_TZ = ZoneInfo("America/Argentina/Buenos_Aires")


def completed_months_between(start: date, end: date) -> int:
    """Return nonnegative completed months between two calendar dates."""
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        months -= 1
    return max(0, months)


def today_in_argentina() -> date:
    return datetime.now(ARGENTINA_TZ).date()


def is_future_date(v: datetime) -> bool:
    """Compare calendar dates only, tolerant of client clock drift."""
    return v.astimezone(ARGENTINA_TZ).date() > today_in_argentina()


def validate_not_future_datetime(v: datetime) -> datetime:
    """Reject datetimes whose calendar date is ahead of today in Argentina."""
    if is_future_date(v):
        raise ValueError("cannot be in the future")
    return v


def validate_not_future_date(v: date | None) -> date | None:
    """Reject dates ahead of today in Argentina, passing None through."""
    if v is not None and v > today_in_argentina():
        raise ValueError("cannot be in the future")
    return v


def month_bounds(year: int, month: int) -> tuple[datetime, datetime]:
    """Return the start of a month and of the next one, in Argentina time."""
    start = datetime(year, month, 1, tzinfo=ARGENTINA_TZ)
    end = (
        datetime(year + 1, 1, 1, tzinfo=ARGENTINA_TZ)
        if month == 12
        else datetime(year, month + 1, 1, tzinfo=ARGENTINA_TZ)
    )
    return start, end
