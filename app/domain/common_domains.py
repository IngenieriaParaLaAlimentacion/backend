from dataclasses import dataclass
from uuid import UUID


@dataclass
class IdentifierRefDomain:
    """Base domain for resources that to expose id and name."""

    id: UUID
    name: str
