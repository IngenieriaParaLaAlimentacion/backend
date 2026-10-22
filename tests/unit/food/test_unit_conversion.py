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
UNIT_WEIGHT_50 = ConversionFactors(unit_weight_g=Decimal("50"))
UNIT_WEIGHT_57_3 = ConversionFactors(unit_weight_g=Decimal("57.3"))
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
        # units go through the weight of one unit
        ("12", UN, UNIT_WEIGHT_50, "600"),
        ("1", UN, UNIT_WEIGHT_50, "50"),
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
        # units go through the weight of one unit and are counted whole
        ("600", UN, UNIT_WEIGHT_50, "12"),
        ("610", UN, UNIT_WEIGHT_50, "12"),
        ("640", UN, UNIT_WEIGHT_50, "13"),
        ("20", UN, UNIT_WEIGHT_50, "0"),
        ("625", UN, UNIT_WEIGHT_50, "12"),
        ("675", UN, UNIT_WEIGHT_50, "14"),
    ],
)
def test_from_grams_converts_to_rounded_base_quantity(
    grams, base_unit, factors, expected_quantity
):
    """Grams convert to the base unit, rounded half-to-even to three decimals
    for kilograms and litres and to a whole number for units."""
    result = from_grams(Decimal(grams), base_unit, factors)

    assert result == Converted(Decimal(expected_quantity))


@pytest.mark.parametrize("convert", [to_grams, from_grams])
@pytest.mark.parametrize(
    ("base_unit", "factors", "reason"),
    [
        # each base unit needs its own factor; the other one does not stand in
        (L, UNIT_WEIGHT_50, ConversionFailure.MISSING_DENSITY),
        (UN, DENSITY_1_03, ConversionFailure.MISSING_UNIT_WEIGHT),
    ],
)
def test_conversion_reports_why_it_cannot_convert(convert, base_unit, factors, reason):
    """A quantity missing the factor it needs gets no value, only the reason."""
    result = convert(Decimal(1), base_unit, factors)

    assert result == Unconverted(reason)


@pytest.mark.parametrize(
    ("base_unit", "factors", "quantity"),
    [
        *[(KG, NO_FACTORS, q) for q in ("2", "0.25", "0.001", "123.456")],
        *[(L, DENSITY_1_03, q) for q in ("2", "0.333", "0.001", "123.456")],
        *[(L, DENSITY_0_917, q) for q in ("2", "0.333", "0.001", "123.456")],
        *[(UN, UNIT_WEIGHT_50, q) for q in ("12", "1", "0", "250")],
        *[(UN, UNIT_WEIGHT_57_3, q) for q in ("12", "1", "0", "250")],
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
