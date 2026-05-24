from dataclasses import dataclass
from datetime import date
from enum import Enum
from uuid import UUID


class Sex(str, Enum):
    """Biological sex of a subject."""

    MALE = "male"
    FEMALE = "female"


@dataclass
class SubjectDomain:
    """Core subject data as returned from persistence."""

    id: UUID
    dni: int
    sex: Sex
    name: str
    last_name: str
    birth_date: date
    is_rural: bool
    is_indigenous: bool

    @classmethod
    def from_orm(cls, obj) -> "SubjectDomain":
        """Build a SubjectDomain from an ORM Subject instance."""
        return cls(**{field: getattr(obj, field) for field in cls.__dataclass_fields__})
