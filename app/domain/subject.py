from dataclasses import dataclass, fields
from datetime import date
from enum import Enum
from uuid import UUID


class Sex(str, Enum):
    """Biological sex of a subject."""

    MALE = "male"
    FEMALE = "female"


@dataclass
class SubjectBase:
    """Base information about a subject."""

    id: UUID
    dni: int
    sex: Sex
    name: str
    last_name: str

    @classmethod
    def from_orm(cls, obj) -> "SubjectBase":
        """Build an instance from an ORM object by matching field names."""
        return cls(**{f.name: getattr(obj, f.name) for f in fields(cls)})


@dataclass
class SubjectDomain(SubjectBase):
    """Full subject data as returned from persistence."""

    birth_date: date
    is_rural: bool
    is_indigenous: bool
