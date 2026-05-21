from dataclasses import dataclass
from uuid import UUID


@dataclass
class EstablishmentDomain:
    """Establishment data as returned from persistence."""

    id: UUID
    name: str
    address: str
