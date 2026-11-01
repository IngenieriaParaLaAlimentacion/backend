from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.domain.food_intake import FoodLineDomain


class FoodOutflowSource(StrEnum):
    """How a food outflow was loaded into the system."""

    MANUAL = "manual"
    PHOTO = "photo"


class FoodOutflowCategory(StrEnum):
    """Why food left an establishment's stock."""

    FAMILY_DELIVERY = "family_delivery"
    KITCHEN = "kitchen"
    DISCARD = "discard"
    OTHER = "other"


@dataclass
class FoodOutflowDomain:
    """A food outflow with its lines, as returned after registering one."""

    id: UUID
    establishment_id: UUID
    responsible_id: UUID
    occurred_at: datetime
    comments: str | None
    category: FoodOutflowCategory
    source: FoodOutflowSource
    created_at: datetime
    items: list[FoodLineDomain]

    @classmethod
    def from_db(cls, outflow) -> "FoodOutflowDomain":
        """Build from an outflow row with ``items`` (each with its food) loaded."""
        return cls(
            id=outflow.id,
            establishment_id=outflow.establishment_id,
            responsible_id=outflow.responsible_id,
            occurred_at=outflow.occurred_at,
            comments=outflow.comments,
            category=outflow.category,
            source=outflow.source,
            created_at=outflow.created_at,
            items=[FoodLineDomain.from_db(item) for item in outflow.items],
        )
