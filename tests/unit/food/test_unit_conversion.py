from decimal import Decimal

import pytest

from app.domain.food_catalog import MeasurementUnit
from app.domain.printed_unit import PrintedUnit as P
from app.domain.unit_conversion import (
    ConversionFactors,
    ConversionFailure,
    Converted,
    Unconverted,
    _printed_to_base_unit,
    from_grams,
    prefill_from_printed,
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
        # units go through the weight of one unit
        ("600", UN, UNIT_WEIGHT_50, "12"),
        ("75", UN, UNIT_WEIGHT_50, "1.5"),
        # never rounded: the caller decides how to round
        ("1234.5678", KG, NO_FACTORS, "1.2345678"),
        ("20", UN, UNIT_WEIGHT_50, "0.4"),
    ],
)
def test_from_grams_converts_to_base_quantity(
    grams, base_unit, factors, expected_quantity
):
    """Grams convert to the base unit without rounding."""
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


@pytest.mark.parametrize("convert", [to_grams, from_grams])
@pytest.mark.parametrize("base_unit", list(MeasurementUnit))
def test_every_base_unit_converts_given_its_factors(convert, base_unit):
    """Every base unit a food can be stocked in has a conversion rule."""
    result = convert(Decimal(1), base_unit, ALL_FACTORS)

    assert isinstance(result, Converted)


@pytest.mark.parametrize(
    ("quantity", "printed_unit", "base_unit", "factors", "expected_quantity"),
    [
        # the same dimension converts with no factor at all
        ("500", P.GRAMOS, KG, NO_FACTORS, "0.5"),
        ("2", P.KILOGRAMOS, KG, NO_FACTORS, "2"),
        ("500", P.MILILITROS, L, NO_FACTORS, "0.5"),
        ("50", P.CENTILITROS, L, NO_FACTORS, "0.5"),
        ("1.5", P.LITROS, L, NO_FACTORS, "1.5"),
        ("3", P.UNIDADES, UN, NO_FACTORS, "3"),
        # rounded as a stored quantity of the base unit
        ("1234.5678", P.GRAMOS, KG, NO_FACTORS, "1.235"),
        ("2.5", P.UNIDADES, UN, NO_FACTORS, "2"),
        ("0.0005", P.KILOGRAMOS, KG, NO_FACTORS, "0"),
        ("0.0015", P.KILOGRAMOS, KG, NO_FACTORS, "0.002"),
        # another dimension goes through grams
        ("600", P.GRAMOS, UN, UNIT_WEIGHT_50, "12"),
        # ties round to the even neighbour
        ("625", P.GRAMOS, UN, UNIT_WEIGHT_50, "12"),
        ("675", P.GRAMOS, UN, UNIT_WEIGHT_50, "14"),
        ("1", P.KILOGRAMOS, L, DENSITY_1_03, "0.971"),
        ("500", P.MILILITROS, KG, DENSITY_1_03, "0.515"),
        ("1", P.LITROS, UN, ALL_FACTORS, "21"),
        ("3", P.UNIDADES, KG, UNIT_WEIGHT_50, "0.15"),
        ("2", P.UNIDADES, L, ALL_FACTORS, "0.097"),
    ],
)
def test_printed_to_base_unit_converts_printed_quantity(
    quantity, printed_unit, base_unit, factors, expected_quantity
):
    """A receipt-printed quantity converts to the food's base unit."""
    result = _printed_to_base_unit(Decimal(quantity), printed_unit, base_unit, factors)

    assert result == Converted(Decimal(expected_quantity))


@pytest.mark.parametrize(
    ("printed_unit", "base_unit", "factors", "reason"),
    [
        (None, KG, ALL_FACTORS, ConversionFailure.UNSUPPORTED_UNIT),
        # the factor the printed unit needs is missing
        (P.UNIDADES, KG, DENSITY_1_03, ConversionFailure.MISSING_UNIT_WEIGHT),
        (P.LITROS, KG, UNIT_WEIGHT_50, ConversionFailure.MISSING_DENSITY),
        # the factor the base unit needs is missing
        (P.GRAMOS, UN, DENSITY_1_03, ConversionFailure.MISSING_UNIT_WEIGHT),
        (P.GRAMOS, L, UNIT_WEIGHT_50, ConversionFailure.MISSING_DENSITY),
    ],
)
def test_printed_to_base_unit_reports_why_it_cannot_convert(
    printed_unit, base_unit, factors, reason
):
    """A printed quantity that cannot be converted gets no value, only the reason."""
    result = _printed_to_base_unit(Decimal(1), printed_unit, base_unit, factors)

    assert result == Unconverted(reason)


@pytest.mark.parametrize("printed_unit", list(P))
@pytest.mark.parametrize("base_unit", list(MeasurementUnit))
def test_every_printed_unit_converts_given_its_factors(printed_unit, base_unit):
    """Every unit a receipt can print converts to every base unit."""
    result = _printed_to_base_unit(Decimal(1), printed_unit, base_unit, ALL_FACTORS)

    assert isinstance(result, Converted)


@pytest.mark.parametrize(
    ("quantity", "unit_text", "base_unit", "factors", "expected"),
    [
        # printed in the food's own base unit
        ("1", "kg", KG, NO_FACTORS, ("1", KG)),
        ("2", "L", L, NO_FACTORS, ("2", L)),
        ("3", "un", UN, NO_FACTORS, ("3", UN)),
        # the printed spelling varies, the result does not
        ("1.5", " Lts. ", L, NO_FACTORS, ("1.5", L)),
        ("0.25", "KG.", KG, NO_FACTORS, ("0.25", KG)),
        # the same dimension as the base unit converts with no factor
        ("500", "g", KG, NO_FACTORS, ("0.5", KG)),
        ("900", "ml", L, NO_FACTORS, ("0.9", L)),
        ("33", "cl", L, NO_FACTORS, ("0.33", L)),
        # another dimension converts with the factors it needs
        ("1", "kg", UN, UNIT_WEIGHT_50, ("20", UN)),
        ("1", "l", KG, DENSITY_1_03, ("1.03", KG)),
        ("3", "un", L, ALL_FACTORS, ("0.146", L)),
        # ...and is not prefilled without them
        ("1", "kg", UN, NO_FACTORS, None),
        ("1", "l", KG, NO_FACTORS, None),
        ("3", "un", L, NO_FACTORS, None),
        # unit text that cannot be used
        ("1", "cucharada", KG, ALL_FACTORS, None),
        ("1", "xyz", UN, ALL_FACTORS, None),
        ("3", "", UN, ALL_FACTORS, None),
        ("3", None, UN, ALL_FACTORS, None),
        # no usable quantity
        (None, "kg", KG, NO_FACTORS, None),
        ("0", "kg", KG, NO_FACTORS, None),
        ("-1", "kg", KG, NO_FACTORS, None),
        # a converted quantity a line cannot hold: zero, or too many digits
        ("20", "g", UN, UNIT_WEIGHT_50, None),
        ("0.4", "g", KG, NO_FACTORS, None),
        ("9999999", "l", KG, DENSITY_1_03, None),
    ],
)
def test_prefill_from_printed(quantity, unit_text, base_unit, factors, expected):
    """A printed quantity is prefilled converted to the food's base unit when
    it has a valid amount, a usable unit and the factors the conversion needs,
    and the result fits a line; otherwise nothing is."""
    result = prefill_from_printed(
        Decimal(quantity) if quantity is not None else None,
        unit_text,
        base_unit,
        factors,
    )

    assert result == (
        (Decimal(expected[0]), expected[1]) if expected is not None else None
    )


@pytest.mark.parametrize("field", ["density_g_ml", "unit_weight_g"])
@pytest.mark.parametrize("value", ["0", "-1"])
def test_conversion_factors_reject_non_positive_values(field, value):
    """A factor that is zero or negative is rejected."""
    with pytest.raises(ValueError):
        ConversionFactors(**{field: Decimal(value)})
