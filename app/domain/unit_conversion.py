from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from enum import StrEnum
from typing import assert_never

from app.domain.food_catalog import MeasurementUnit


class ConversionFailure(StrEnum):
    """Why a quantity could not be converted."""

    MISSING_DENSITY = "missing_density"
    MISSING_UNIT_WEIGHT = "missing_unit_weight"


@dataclass(frozen=True)
class ConversionFactors:
    """A food's known equivalences; None means the food has none of that kind.

    Raises:
        ValueError: a factor is given and is not positive.
    """

    density_g_ml: Decimal | None = None
    unit_weight_g: Decimal | None = None

    def __post_init__(self) -> None:
        for name in ("density_g_ml", "unit_weight_g"):
            value = getattr(self, name)
            if value is not None and value <= 0:
                raise ValueError(f"{name} must be positive, got {value}")


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
MILLILITRES_PER_LITRE = Decimal(1000)

# Kilograms and litres are persisted as Numeric(10, 3); units are counted whole.
_BASE_UNIT_QUANTUM: dict[MeasurementUnit, Decimal] = {
    MeasurementUnit.KILOGRAMOS: Decimal("0.001"),
    MeasurementUnit.LITROS: Decimal("0.001"),
    MeasurementUnit.UNIDADES: Decimal(1),
}


def to_grams(
    quantity: Decimal, base_unit: MeasurementUnit, factors: ConversionFactors
) -> ConversionResult:
    """Convert ``quantity`` of a food's ``base_unit`` to grams.

    Kilograms need no factor, litres need ``factors.density_g_ml`` and units
    need ``factors.unit_weight_g``. A missing factor is returned as
    ``Unconverted`` with its reason. The result is not rounded.
    """
    grams_per_unit = _grams_per_base_unit(base_unit, factors)
    if isinstance(grams_per_unit, ConversionFailure):
        return Unconverted(grams_per_unit)
    return Converted(quantity * grams_per_unit)


def from_grams(
    grams: Decimal, base_unit: MeasurementUnit, factors: ConversionFactors
) -> ConversionResult:
    """Convert ``grams`` of a food to its ``base_unit``.

    Kilograms need no factor, litres need ``factors.density_g_ml`` and units
    need ``factors.unit_weight_g``. A missing factor is returned as
    ``Unconverted`` with its reason. The result is rounded half-to-even to
    three decimals, or to a whole number for units.
    """
    grams_per_unit = _grams_per_base_unit(base_unit, factors)
    if isinstance(grams_per_unit, ConversionFailure):
        return Unconverted(grams_per_unit)
    return Converted(_round_base_quantity(grams / grams_per_unit, base_unit))


def _grams_per_base_unit(
    base_unit: MeasurementUnit, factors: ConversionFactors
) -> Decimal | ConversionFailure:
    """Return the grams one ``base_unit`` of the food weighs, or why it is unknown."""
    match base_unit:
        case MeasurementUnit.KILOGRAMOS:
            return GRAMS_PER_KILOGRAM
        case MeasurementUnit.LITROS:
            if factors.density_g_ml is None:
                return ConversionFailure.MISSING_DENSITY
            return MILLILITRES_PER_LITRE * factors.density_g_ml
        case MeasurementUnit.UNIDADES:
            if factors.unit_weight_g is None:
                return ConversionFailure.MISSING_UNIT_WEIGHT
            return factors.unit_weight_g
        case _:
            # A new base unit must get its own rule here before it can convert.
            assert_never(base_unit)


def _round_base_quantity(quantity: Decimal, base_unit: MeasurementUnit) -> Decimal:
    """Round a quantity half-to-even to the precision ``base_unit`` is kept in."""
    # Half-to-even keeps tie roundings from drifting a stock balance upwards.
    return quantity.quantize(_BASE_UNIT_QUANTUM[base_unit], rounding=ROUND_HALF_EVEN)
