from dataclasses import dataclass
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
    address: str


@dataclass
class EstablishmentWithStatusDomain(EstablishmentDomain):
    """Establishment data with its approval status in the context of a manager."""

    status: str
