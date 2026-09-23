from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.food_catalog import MeasurementUnit
from app.schemas.common import IdentifierRefSchema


class ProposedFoodLine(BaseModel):
    """One food line the extractor proposes from the receipt.

    ``food`` is the catalog match. When it is null the line was read but not
    recognised, ``needs_review`` is true, and the user has to pick a catalog
    food (or drop the line) before the intake can be confirmed.
    """

    model_config = ConfigDict(from_attributes=True)

    description: str = Field(
        description="The item text as read from the receipt.",
    )
    food: IdentifierRefSchema | None = Field(
        default=None,
        description="Matched catalog food, or null when nothing matched.",
    )
    quantity: Decimal | None = Field(
        default=None,
        max_digits=10,
        decimal_places=3,
        description="Detected quantity in the matched food's base unit, if any.",
    )
    unit: MeasurementUnit | None = Field(
        default=None,
        description="Base unit of the matched catalog food; null when unmatched.",
    )
    raw_quantity: Decimal | None = Field(
        default=None,
        max_digits=10,
        decimal_places=3,
        description=(
            "Quantity as printed on the receipt, before any catalog "
            "matching or unit conversion. Null when the receipt line does "
            "not specify one."
        ),
    )
    raw_unit_text: str | None = Field(
        default=None,
        description=(
            "Unit text as printed next to raw_quantity on the receipt "
            "(e.g. 'kg', 'un', 'L'), verbatim. Null when raw_quantity is null "
            "or the receipt gives a bare count with no unit."
        ),
    )
    needs_review: bool = Field(
        description="True when the user must fix this line before confirming.",
    )


class ReceiptProposalResponse(BaseModel):
    """The assisted proposal for a receipt photo, before confirmation."""

    establishment_id: UUID
    lines: list[ProposedFoodLine] = Field(
        default_factory=list,
        description="Proposed food lines; empty when nothing was detected.",
    )
    message: str | None = Field(
        default=None,
        description=(
            "Human-readable note, e.g. a hint to fall back to manual entry "
            "when no items were detected."
        ),
    )
