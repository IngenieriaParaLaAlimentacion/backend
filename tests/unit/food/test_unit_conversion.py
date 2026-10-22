from decimal import Decimal

import pytest

from app.domain.food_catalog import MeasurementUnit
from app.domain.unit_conversion import (
    ConversionFactors,
    ConversionFailure,
    Converted,
    Unconverted,
    from_grams,
    to_grams,
)

KG = MeasurementUnit.KILOGRAMOS
L = MeasurementUnit.LITROS
UN = MeasurementUnit.UNIDADES

NO_FACTORS = ConversionFactors()
# Made-up test data, not real equivalences.
DENSITY_1_03 = ConversionFactors(density_g_ml=Decimal("1.03"))
DENSITY_0_917 = ConversionFactors(density_g_ml=Decimal("0.917"))
ALL_FACTORS = ConversionFactors(
    density_g_ml=Decimal("1.03"), unit_weight_g=Decimal("50")
)


@pytest.mark.parametrize(
    ("quantity", "base_unit", "factors", "expected_grams"),
    [
        # kilograms need no factor, and ignore any the food has
        ("2", KG, NO_FACTORS, "2000"),
        ("0.25", KG, NO_FACTORS, "250"),
        ("0.001", KG, NO_FACTORS, "1"),
        ("0", KG, NO_FACTORS, "0"),
        ("2", KG, ALL_FACTORS, "2000"),
        # litres go through the density
        ("2", L, DENSITY_1_03, "2060"),
        ("0.5", L, DENSITY_1_03, "515"),
        ("0.001", L, DENSITY_1_03, "1.03"),
    ],
)
def test_to_grams_converts_base_quantity(quantity, base_unit, factors, expected_grams):
    """A base-unit quantity converts to grams."""
    result = to_grams(Decimal(quantity), base_unit, factors)

    assert result == Converted(Decimal(expected_grams))


@pytest.mark.parametrize(
    ("grams", "base_unit", "factors", "expected_quantity"),
    [
        # kilograms need no factor, and ignore any the food has
        ("2000", KG, NO_FACTORS, "2"),
        ("250", KG, NO_FACTORS, "0.25"),
        ("1", KG, NO_FACTORS, "0.001"),
        ("0", KG, NO_FACTORS, "0"),
        ("2000", KG, ALL_FACTORS, "2"),
        # litres go through the density
        ("2060", L, DENSITY_1_03, "2"),
        ("515", L, DENSITY_1_03, "0.5"),
        # more decimals than a stored quantity holds: 1000 / 1030 = 0.97087...
        ("1000", L, DENSITY_1_03, "0.971"),
        ("1234.5678", KG, NO_FACTORS, "1.235"),
        ("0.4", KG, NO_FACTORS, "0"),
        # ties round to the even neighbour
        ("0.5", KG, NO_FACTORS, "0"),
        ("1.5", KG, NO_FACTORS, "0.002"),
    ],
)
def test_from_grams_converts_to_base_quantity_with_three_decimals(
    grams, base_unit, factors, expected_quantity
):
    """Grams convert to the base unit, rounded half-to-even to three decimals."""
    result = from_grams(Decimal(grams), base_unit, factors)

    assert result == Converted(Decimal(expected_quantity))
    # Stored quantities are Numeric(10, 3), so the scale is always three.
    assert result.value.as_tuple().exponent == -3


@pytest.mark.parametrize("convert", [to_grams, from_grams])
@pytest.mark.parametrize(
    ("base_unit", "factors", "reason"),
    [
        (L, NO_FACTORS, ConversionFailure.MISSING_DENSITY),
        (UN, ALL_FACTORS, ConversionFailure.UNSUPPORTED_UNIT),
    ],
)
def test_conversion_reports_why_it_cannot_convert(convert, base_unit, factors, reason):
    """A quantity that cannot be converted gets no value, only the reason."""
    result = convert(Decimal(1), base_unit, factors)

    assert result == Unconverted(reason)


@pytest.mark.parametrize(
    ("base_unit", "factors", "quantity"),
    [
        *[(KG, NO_FACTORS, q) for q in ("2", "0.25", "0.001", "123.456")],
        *[(L, DENSITY_1_03, q) for q in ("2", "0.333", "0.001", "123.456")],
        *[(L, DENSITY_0_917, q) for q in ("2", "0.333", "0.001", "123.456")],
    ],
)
def test_base_quantity_survives_a_round_trip_through_grams(
    base_unit, factors, quantity
):
    """Converting a base-unit quantity to grams and back returns it unchanged."""
    grams = to_grams(Decimal(quantity), base_unit, factors)

    result = from_grams(grams.value, base_unit, factors)

    assert result == Converted(Decimal(quantity))


@pytest.mark.parametrize("field", ["density_g_ml", "unit_weight_g"])
@pytest.mark.parametrize("value", ["0", "-1"])
def test_conversion_factors_reject_non_positive_values(field, value):
    """A factor that is zero or negative is rejected."""
    with pytest.raises(ValueError):
        ConversionFactors(**{field: Decimal(value)})
