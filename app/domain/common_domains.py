from dataclasses import dataclass
from uuid import UUID


def normalize_optional_str(value: str | None) -> str | None:
    """Strip a string field, collapsing blank/whitespace-only input to None."""
    return value.strip() or None if value else None


@dataclass
class IdentifierRefDomain:
    """Base domain for resources that to expose id and name."""

    id: UUID
    name: str

    @classmethod
    def from_db(cls, obj) -> "IdentifierRefDomain":
        return cls(id=obj.id, name=obj.name)
