import math
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime


def retry_after_seconds(value: str | None) -> int | None:
    """Parse an upstream Retry-After value without inventing a reset time."""
    if not value:
        return None
    try:
        if value.strip().isdigit():
            seconds = int(value)
        else:
            parsed = parsedate_to_datetime(value)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            seconds = math.ceil((parsed - datetime.now(timezone.utc)).total_seconds())
        return seconds if 0 < seconds <= 604800 else None
    except (ValueError, OverflowError, TypeError):
        return None
