from decimal import Decimal

import pytest

from app.domain.food_catalog import MeasurementUnit
from app.domain.unit_conversion import (
    ConversionFailure,
    Converted,
    Unconverted,
    from_grams,
    to_grams,
)


@pytest.mark.parametrize(
    ("kilograms", "expected_grams"),
    [
        ("2", "2000"),
        ("0.25", "250"),
        ("0.001", "1"),
        ("0", "0"),
    ],
)
def test_to_grams_converts_kilograms(kilograms, expected_grams):
    """Kilograms convert to grams without any per-food data."""
    result = to_grams(Decimal(kilograms), MeasurementUnit.KILOGRAMOS)

    assert result == Converted(Decimal(expected_grams))


@pytest.mark.parametrize(
    "base_unit", [MeasurementUnit.LITROS, MeasurementUnit.UNIDADES]
)
def test_to_grams_leaves_other_base_units_unconverted(base_unit):
    """Litres and units are not converted and report why."""
    result = to_grams(Decimal(1), base_unit)

    assert result == Unconverted(ConversionFailure.UNSUPPORTED_UNIT)


@pytest.mark.parametrize(
    ("grams", "expected_kilograms"),
    [
        ("2000", "2"),
        ("250", "0.25"),
        ("1", "0.001"),
        ("0", "0"),
    ],
)
def test_from_grams_converts_to_kilograms(grams, expected_kilograms):
    """Grams convert to kilograms without any per-food data."""
    result = from_grams(Decimal(grams), MeasurementUnit.KILOGRAMOS)

    assert result == Converted(Decimal(expected_kilograms))


@pytest.mark.parametrize(
    ("grams", "expected_kilograms"),
    [
        # more decimals than a stored quantity holds
        ("1234.5678", "1.235"),
        ("0.4", "0.000"),
        # ties round to the even neighbour
        ("0.5", "0.000"),
        ("1.5", "0.002"),
    ],
)
def test_from_grams_rounds_half_even_to_three_decimals(grams, expected_kilograms):
    """The base-unit result is rounded half-to-even to three decimals."""
    result = from_grams(Decimal(grams), MeasurementUnit.KILOGRAMOS)

    assert result == Converted(Decimal(expected_kilograms))
    assert result.value.as_tuple().exponent == -3


@pytest.mark.parametrize(
    "base_unit", [MeasurementUnit.LITROS, MeasurementUnit.UNIDADES]
)
def test_from_grams_leaves_other_base_units_unconverted(base_unit):
    """Grams are not converted to litres or units and report why."""
    result = from_grams(Decimal(1), base_unit)

    assert result == Unconverted(ConversionFailure.UNSUPPORTED_UNIT)


@pytest.mark.parametrize("kilograms", ["2", "0.25", "0.001", "123.456"])
def test_kilograms_survive_a_round_trip_through_grams(kilograms):
    """Converting kilograms to grams and back returns the same quantity."""
    grams = to_grams(Decimal(kilograms), MeasurementUnit.KILOGRAMOS)

    result = from_grams(grams.value, MeasurementUnit.KILOGRAMOS)

    assert result == Converted(Decimal(kilograms))
