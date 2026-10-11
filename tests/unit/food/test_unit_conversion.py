from decimal import Decimal

import pytest

from app.domain.food_catalog import MeasurementUnit
from app.domain.unit_conversion import convert_to_base_unit

KG = MeasurementUnit.KILOGRAMOS
L = MeasurementUnit.LITROS
UN = MeasurementUnit.UNIDADES


@pytest.mark.parametrize(
    ("quantity", "unit_text", "base_unit", "expected"),
    [
        # same unit as the catalog's
        ("1", "kg", KG, "1"),
        ("2", "L", L, "2"),
        ("3", "un", UN, "3"),
        # same dimension, different scale
        ("500", "g", KG, "0.5"),
        ("900", "ml", L, "0.9"),
        ("33", "cl", L, "0.33"),
        # printed spelling varies
        ("250", "GR.", KG, "0.25"),
        ("1.5", " Lts ", L, "1.5"),
        # a bare count is a count of units
        ("3", None, UN, "3"),
        ("3", "", UN, "3"),
        # no quantity, nothing to prefill
        (None, "kg", KG, None),
        (None, None, UN, None),
        # different dimension than the catalog's
        ("1", "kg", UN, None),
        ("1", "kg", L, None),
        ("500", "ml", KG, None),
        ("3", None, KG, None),
        # unit text we cannot interpret
        ("1", "docena", UN, None),
        ("1", "xyz", KG, None),
        # converts to less than the stored precision
        ("0.0001", "g", KG, None),
    ],
)
def test_convert_to_base_unit(quantity, unit_text, base_unit, expected):
    """A printed quantity converts to the food's base unit only when the two
    measure the same dimension; otherwise nothing is prefilled."""
    result = convert_to_base_unit(
        Decimal(quantity) if quantity is not None else None, unit_text, base_unit
    )

    assert result == (Decimal(expected) if expected is not None else None)
