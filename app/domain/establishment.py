from dataclasses import dataclass, fields
from enum import Enum, StrEnum
from uuid import UUID


class UserEstablishmentStatus(str, Enum):
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
    """Establishment data with its approval status in the context of a manager."""

    status: str
