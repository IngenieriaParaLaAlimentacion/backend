from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID


class SubjectEventType(StrEnum):
    """All possible subject lifecycle event types recorded in the audit log."""

    SUBJECT_CREATED = "SUBJECT_CREATED"
    SUBJECT_UPDATED = "SUBJECT_UPDATED"


@dataclass
class EventPayload:
    """Caller-defined payload attached to a subject event.

    Both fields are None for events with no meaningful before/after state
    (e.g. creation).
    """

    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None


@dataclass
class SubjectEventRecord:
    """A single subject event as returned by the repository."""

    event_type: SubjectEventType
    occurred_at: datetime
    actor_id: UUID
    payload: EventPayload

    @classmethod
    def from_db(cls, obj) -> "SubjectEventRecord":
        return cls(
            event_type=obj.event_type,
            occurred_at=obj.occurred_at,
            actor_id=obj.actor_id,
            payload=EventPayload(
                before=obj.payload.get("before"),
                after=obj.payload.get("after"),
            )
            if obj.payload
            else EventPayload(),
        )
