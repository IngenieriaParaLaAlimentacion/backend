from dataclasses import dataclass, fields
from enum import Enum
from uuid import UUID


class UserEstablishmentStatus(str, Enum):
    APPROVED = "approved"
    PENDING = "pending"
    REJECTED = "rejected"


@dataclass
class EstablishmentDomain:
    """Establishment data as returned from persistence."""

    id: UUID
    name: str
    formatted_address: str
    latitude: float | None
    longitude: float | None
    place_id: str | None
    city: str | None
    province: str | None

    @classmethod
    def from_orm(cls, obj) -> "EstablishmentDomain":
        return cls(**{field.name: getattr(obj, field.name) for field in fields(cls)})


@dataclass
class EstablishmentWithStatusDomain(EstablishmentDomain):
    """Establishment data with its approval status in the context of a manager."""

    status: str
