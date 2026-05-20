from dataclasses import dataclass
from uuid import UUID


@dataclass
class EstablishmentDomain:
    id: UUID
    name: str
    address: str
