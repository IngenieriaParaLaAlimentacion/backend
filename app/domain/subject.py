from dataclasses import dataclass
from datetime import date
from enum import Enum, StrEnum
from typing import Any
from uuid import UUID


class Sex(str, Enum):
    """Biological sex of a subject."""

    MALE = "male"
    FEMALE = "female"


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
class SubjectBase:
    """Base information about a subject."""

    id: UUID
    dni: int
    sex: Sex
    name: str
    last_name: str


@dataclass
class SubjectDomain(SubjectBase):
    """Full subject data as returned from persistence."""

    birth_date: date
    is_rural: bool
    is_indigenous: bool

    @classmethod
    def from_orm(cls, obj) -> "SubjectDomain":
        """Build a SubjectDomain from an ORM Subject instance."""
        return cls(**{field: getattr(obj, field) for field in cls.__dataclass_fields__})
