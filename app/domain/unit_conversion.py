from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from enum import StrEnum

from app.domain.food_catalog import MeasurementUnit


class ConversionFailure(StrEnum):
    """Why a quantity could not be converted."""

    UNSUPPORTED_UNIT = "unsupported_unit"


@dataclass(frozen=True)
class Converted:
    """A quantity that was converted, expressed in the target unit."""

    value: Decimal


@dataclass(frozen=True)
class Unconverted:
    """A quantity that could not be converted, and why."""

    reason: ConversionFailure


ConversionResult = Converted | Unconverted

GRAMS_PER_KILOGRAM = Decimal(1000)

# Base-unit quantities are persisted as Numeric(10, 3).
_BASE_UNIT_QUANTUM = Decimal("0.001")


def to_grams(quantity: Decimal, base_unit: MeasurementUnit) -> ConversionResult:
    """Convert ``quantity`` of a food's ``base_unit`` to grams.

    Only ``KILOGRAMOS`` is converted. Any other unit is returned as
    ``Unconverted`` with ``UNSUPPORTED_UNIT``.
    """
    if base_unit is MeasurementUnit.KILOGRAMOS:
        return Converted(quantity * GRAMS_PER_KILOGRAM)
    return Unconverted(ConversionFailure.UNSUPPORTED_UNIT)


def from_grams(grams: Decimal, base_unit: MeasurementUnit) -> ConversionResult:
    """Convert ``grams`` of a food to its ``base_unit``.

    The result is rounded half-to-even to three decimals. Only ``KILOGRAMOS``
    is converted. Any other unit is returned as ``Unconverted`` with
    ``UNSUPPORTED_UNIT``.
    """
    if base_unit is MeasurementUnit.KILOGRAMOS:
        return Converted(_round_base_quantity(grams / GRAMS_PER_KILOGRAM))
    return Unconverted(ConversionFailure.UNSUPPORTED_UNIT)


def _round_base_quantity(quantity: Decimal) -> Decimal:
    """Round a base-unit quantity half-to-even to three decimals."""
    # Half-to-even keeps tie roundings from drifting a stock balance upwards.
    return quantity.quantize(_BASE_UNIT_QUANTUM, rounding=ROUND_HALF_EVEN)
