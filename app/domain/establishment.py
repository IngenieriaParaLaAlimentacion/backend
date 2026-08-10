from dataclasses import dataclass, fields
from datetime import datetime
from enum import Enum, StrEnum
from uuid import UUID


class UserEstablishmentStatus(str, Enum):
    APPROVED = "approved"
    PENDING = "pending"
    REJECTED = "rejected"


# TODO:check if we can reuse user status for establishments,
# to have somthing like a StatusEnum
class EstablishmentRequestStatus(StrEnum):
    APPROVED = "approved"
    PENDING = "pending"
    REJECTED = "rejected"


class EstablishmentSortOrder(StrEnum):
    NEWEST = "newest"
    OLDEST = "oldest"
    NAME_ASC = "name_asc"
    NAME_DESC = "name_desc"
    CITY_ASC = "city_asc"
    CITY_DESC = "city_desc"
    PROVINCE_ASC = "province_asc"
    PROVINCE_DESC = "province_desc"


@dataclass
class EstablishmentListingParams:
    """Query parameters for a paginated establishment listing."""

    search: str | None = None
    city: str | None = None
    province: str | None = None
    sort_order: EstablishmentSortOrder = EstablishmentSortOrder.NEWEST

    def __post_init__(self) -> None:
        self.search = self.search.strip() or None if self.search else None
        self.city = self.city.strip() or None if self.city else None
        self.province = self.province.strip() or None if self.province else None


@dataclass
class EstablishmentDomain:
    """Establishment data as returned from persistence."""

    id: UUID
    name: str
    formatted_address: str
    latitude: float
    longitude: float
    place_id: str
    city: str
    province: str

    @classmethod
    def from_db(cls, obj) -> "EstablishmentDomain":
        return cls(**{field.name: getattr(obj, field.name) for field in fields(cls)})


@dataclass
class EstablishmentWithStatusDomain(EstablishmentDomain):
    """Establishment data with its approval status in the context of a field worker."""

    status: str


@dataclass
class EstablishmentRequestDomain:
    """Establishment creation request data as returned from persistence."""

    id: UUID
    user_id: UUID
    name: str | None
    formatted_address: str | None
    city: str | None
    province: str | None
    status: str
    created_at: datetime

    @classmethod
    def from_db(cls, obj) -> "EstablishmentRequestDomain":
        return cls(**{field.name: getattr(obj, field.name) for field in fields(cls)})
