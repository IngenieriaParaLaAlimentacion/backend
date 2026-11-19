from enum import StrEnum


class UserBlockEventType(StrEnum):
    """Actions recorded in the audit log of user blocks."""

    BLOCKED = "blocked"
    UNBLOCKED = "unblocked"
