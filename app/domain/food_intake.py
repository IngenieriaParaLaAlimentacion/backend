from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID

from app.domain.common_domains import IdentifierRefDomain
from app.domain.food_catalog import MeasurementUnit
from app.domain.measurement import EstablishmentRefDomain


class FoodIntakeSource(str, Enum):
    """How a food intake was loaded into the system."""

    MANUAL = "manual"
    PHOTO = "photo"


@dataclass
class FoodLineDomain:
    """One food line of a movement, with the unit resolved from the catalog."""

    food: IdentifierRefDomain
    unit: MeasurementUnit
    quantity: Decimal

    @classmethod
    def from_db(cls, item) -> "FoodLineDomain":
        """Build from an item row with its ``food`` loaded."""
        return cls(
            food=IdentifierRefDomain.from_db(item.food),
            unit=item.food.base_unit,
            quantity=item.quantity,
        )


@dataclass
class FoodIntakeDomain:
    """A food intake with its lines, as returned after registering one."""

    id: UUID
    establishment_id: UUID
    responsible_id: UUID
    received_at: datetime
    comments: str | None
    source: FoodIntakeSource
    created_at: datetime
    items: list[FoodLineDomain]

    @classmethod
    def from_db(cls, intake) -> "FoodIntakeDomain":
        """Build from an intake row with ``items`` (each with its food) loaded."""
        return cls(
            id=intake.id,
            establishment_id=intake.establishment_id,
            responsible_id=intake.responsible_id,
            received_at=intake.received_at,
            comments=intake.comments,
            source=intake.source,
            created_at=intake.created_at,
            items=[FoodLineDomain.from_db(item) for item in intake.items],
        )


@dataclass
class FoodMovementListItemDomain:
    """A food intake or outflow row for the activity-feed view.

    One shape serves both directions. The column asymmetry
    (``food_intakes.received_at`` vs ``food_outflows.occurred_at``) is
    normalized to ``occurred_at`` here, the same way the feed's phase-A union
    normalizes it for ordering.

    No responsible reference: ``/me/activity`` is already scoped to the caller,
    matching ``SurveyResponseListItemDomain``. ``items`` are rendered as stored,
    including repeated foods -- a single movement may legally carry two lines
    for the same food, and the feed reports what was recorded, not a rollup.
    """

    id: UUID
    occurred_at: datetime
    comments: str | None
    source: str
    establishment: EstablishmentRefDomain
    items: list[FoodLineDomain]

    @classmethod
    def from_intake(cls, intake) -> "FoodMovementListItemDomain":
        """Build from an intake row with ``establishment`` and ``items``
        (each with its ``food``) loaded."""
        return cls(
            id=intake.id,
            occurred_at=intake.received_at,
            comments=intake.comments,
            source=intake.source,
            establishment=EstablishmentRefDomain.from_db(intake.establishment),
            items=[FoodLineDomain.from_db(item) for item in intake.items],
        )

    @classmethod
    def from_outflow(cls, outflow) -> "FoodMovementListItemDomain":
        """Build from an outflow row with ``establishment`` and ``items``
        (each with its ``food``) loaded."""
        return cls(
            id=outflow.id,
            occurred_at=outflow.occurred_at,
            comments=outflow.comments,
            source=outflow.source,
            establishment=EstablishmentRefDomain.from_db(outflow.establishment),
            items=[FoodLineDomain.from_db(item) for item in outflow.items],
        )
