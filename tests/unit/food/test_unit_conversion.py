from decimal import Decimal

import pytest

from app.domain.food_catalog import MeasurementUnit
from app.domain.unit_conversion import (
    ConversionFailure,
    Converted,
    Unconverted,
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
