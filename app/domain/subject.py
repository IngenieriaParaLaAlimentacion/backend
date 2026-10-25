from dataclasses import dataclass, fields
from datetime import date
from enum import StrEnum
from typing import Self
from uuid import UUID

from app.domain.common_domains import normalize_optional_str


class Sex(StrEnum):
    """Biological sex of a subject."""

    MALE = "male"
    FEMALE = "female"


class SubjectSortOrder(StrEnum):
    """Sort orders accepted by the subject listing."""

    CREATED_AT_DESC = "created_at_desc"
    CREATED_AT_ASC = "created_at_asc"
    NAME_ASC = "name_asc"
    NAME_DESC = "name_desc"
    BIRTH_DATE_ASC = "birth_date_asc"
    BIRTH_DATE_DESC = "birth_date_desc"


@dataclass
class SubjectBase:
    """Base information about a subject."""

    id: UUID
    dni: int
    sex: Sex
    name: str
    last_name: str

    @classmethod
    def from_db(cls, obj) -> Self:
        """Build an instance from an ORM object by matching field names."""
        return cls(**{f.name: getattr(obj, f.name) for f in fields(cls)})


@dataclass
class SubjectDomain(SubjectBase):
    """Full subject data as returned from persistence."""

    birth_date: date
    is_rural: bool
    is_indigenous: bool


@dataclass
class SubjectListingParams:
    """Query parameters for a paginated subject listing."""

    search: str | None = None
    birth_date_from: date | None = None
    birth_date_to: date | None = None
    establishment_id: UUID | None = None
    is_rural: bool | None = None
    is_indigenous: bool | None = None
    sex: Sex | None = None
    sort_order: SubjectSortOrder = SubjectSortOrder.CREATED_AT_DESC

    def __post_init__(self) -> None:
        self.search = normalize_optional_str(self.search)
