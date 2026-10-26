from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, field_validator

from app.domain.food_catalog import MeasurementUnit
from app.domain.printed_quantity import parse_printed_quantity
from app.schemas.common import IdentifierRefSchema


class ProposedFoodLine(BaseModel):
    """One food line the extractor proposes from the receipt.

    ``food`` is the catalog match. When it is null the line was read but not
    recognised, and the user has to pick a catalog food (or drop the line)
    before the intake can be confirmed.
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
        description=(
            "Quantity prefilled from the receipt, in the matched food's base "
            "unit. Null whenever unit is null."
        ),
    )
    unit: MeasurementUnit | None = Field(
        default=None,
        description=(
            "Base unit of the matched catalog food. Null when the line is "
            "unmatched or the printed quantity could not be prefilled as-is."
        ),
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


class ExtractedReceiptLine(BaseModel):
    """A locally validated line read before catalog matching."""

    model_config = ConfigDict(extra="forbid", strict=True)
    description: str
    raw_quantity: FiniteFloat | None = None
    raw_unit_text: str | None = None

    @field_validator("raw_quantity", mode="before")
    @classmethod
    def normalize_printed_quantity(cls, value):
        """Parse printed quantities and discard unusable amounts."""
        return parse_printed_quantity(value)


class ReceiptExtraction(BaseModel):
    """A validated receipt extraction envelope."""

    model_config = ConfigDict(extra="forbid", strict=True)
    lines: list[ExtractedReceiptLine]
