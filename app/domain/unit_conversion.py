from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from enum import Enum, StrEnum
from typing import NamedTuple, assert_never

from app.domain.food_catalog import MeasurementUnit
from app.domain.printed_unit import PrintedUnit


class ConversionFailure(StrEnum):
    """Why a quantity could not be converted."""

    MISSING_DENSITY = "missing_density"
    MISSING_UNIT_WEIGHT = "missing_unit_weight"
    UNSUPPORTED_UNIT = "unsupported_unit"


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


class _Dimension(Enum):
    """What a unit measures, named after the unit its size is counted in."""

    MASS = "grams"
    VOLUME = "millilitres"
    COUNT = "units"


class _Measure(NamedTuple):
    """A unit as its dimension and how many grams, millilitres or units it is."""

    dimension: _Dimension
    size: Decimal


_BASE_UNIT_MEASURE: dict[MeasurementUnit, _Measure] = {
    MeasurementUnit.KILOGRAMOS: _Measure(_Dimension.MASS, Decimal(1000)),
    MeasurementUnit.LITROS: _Measure(_Dimension.VOLUME, Decimal(1000)),
    MeasurementUnit.UNIDADES: _Measure(_Dimension.COUNT, Decimal(1)),
}

_PRINTED_UNIT_MEASURE: dict[PrintedUnit, _Measure] = {
    PrintedUnit.GRAMOS: _Measure(_Dimension.MASS, Decimal(1)),
    PrintedUnit.KILOGRAMOS: _Measure(_Dimension.MASS, Decimal(1000)),
    PrintedUnit.MILILITROS: _Measure(_Dimension.VOLUME, Decimal(1)),
    PrintedUnit.CENTILITROS: _Measure(_Dimension.VOLUME, Decimal(10)),
    PrintedUnit.LITROS: _Measure(_Dimension.VOLUME, Decimal(1000)),
    PrintedUnit.UNIDADES: _Measure(_Dimension.COUNT, Decimal(1)),
}

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
    grams_per_unit = _grams_per(_BASE_UNIT_MEASURE[base_unit], factors)
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
    grams_per_unit = _grams_per(_BASE_UNIT_MEASURE[base_unit], factors)
    if isinstance(grams_per_unit, ConversionFailure):
        return Unconverted(grams_per_unit)
    return Converted(_round_base_quantity(grams / grams_per_unit, base_unit))


def printed_to_base_unit(
    quantity: Decimal,
    printed_unit: PrintedUnit | None,
    base_unit: MeasurementUnit,
    factors: ConversionFactors,
) -> ConversionResult:
    """Convert a quantity printed on a receipt to the food's ``base_unit``.

    A printed unit of the same dimension as ``base_unit`` converts with no
    factor. Any other goes through grams and needs the factors both units
    call for. A missing ``printed_unit`` is returned as ``Unconverted`` with
    ``UNSUPPORTED_UNIT``, and a missing factor with its reason. The result is
    rounded as in ``from_grams``.
    """
    if printed_unit is None:
        return Unconverted(ConversionFailure.UNSUPPORTED_UNIT)

    printed = _PRINTED_UNIT_MEASURE[printed_unit]
    base = _BASE_UNIT_MEASURE[base_unit]
    if printed.dimension is base.dimension:
        return Converted(
            _round_base_quantity(quantity * printed.size / base.size, base_unit)
        )

    grams_per_printed_unit = _grams_per(printed, factors)
    if isinstance(grams_per_printed_unit, ConversionFailure):
        return Unconverted(grams_per_printed_unit)
    return from_grams(quantity * grams_per_printed_unit, base_unit, factors)


def _grams_per(
    measure: _Measure, factors: ConversionFactors
) -> Decimal | ConversionFailure:
    """Return the grams one of ``measure`` of the food weighs, or why it is unknown."""
    match measure.dimension:
        case _Dimension.MASS:
            return measure.size
        case _Dimension.VOLUME:
            if factors.density_g_ml is None:
                return ConversionFailure.MISSING_DENSITY
            return measure.size * factors.density_g_ml
        case _Dimension.COUNT:
            if factors.unit_weight_g is None:
                return ConversionFailure.MISSING_UNIT_WEIGHT
            return measure.size * factors.unit_weight_g
        case _:
            # A new dimension must get its own rule here before it can convert.
            assert_never(measure.dimension)


def _round_base_quantity(quantity: Decimal, base_unit: MeasurementUnit) -> Decimal:
    """Round a quantity half-to-even to the precision ``base_unit`` is kept in."""
    # Half-to-even keeps tie roundings from drifting a stock balance upwards.
    return quantity.quantize(_BASE_UNIT_QUANTUM[base_unit], rounding=ROUND_HALF_EVEN)
