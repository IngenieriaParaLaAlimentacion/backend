from decimal import Decimal

import pytest

from app.domain.food_catalog import MeasurementUnit
from app.domain.printed_unit import (
    PrintedUnit,
    normalize_printed_unit,
    prefill_from_printed,
)

KG = MeasurementUnit.KILOGRAMOS
L = MeasurementUnit.LITROS
UN = MeasurementUnit.UNIDADES


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        *[
            (t, PrintedUnit.GRAMOS)
            for t in ("g", "gr", "grs", "gramo", "gramos", "GR.", " Gr ")
        ],
        *[
            (t, PrintedUnit.KILOGRAMOS)
            for t in ("kg", "kgs", "kilo", "kilos", "kilogramo", "KG.", " Kg ")
        ],
        *[
            (t, PrintedUnit.MILILITROS)
            for t in ("ml", "cc", "mililitro", "mililitros", "ML", "Cc.")
        ],
        *[
            (t, PrintedUnit.CENTILITROS)
            for t in ("cl", "centilitro", "centilitros", "CL.")
        ],
        *[
            (t, PrintedUnit.LITROS)
            for t in ("l", "lt", "lts", "litro", "litros", "L", " Lts. ")
        ],
        *[
            (t, PrintedUnit.UNIDADES)
            for t in ("u", "un", "uni", "unid", "unids", "unidad", "unidades", "UN.")
        ],
    ],
)
def test_normalize_printed_unit_recognises_each_supported_unit(text, expected):
    """Every spelling of a supported unit maps to that unit, ignoring case,
    surrounding whitespace and a trailing dot."""
    assert normalize_printed_unit(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "cucharada",
        "cucharadita",
        "taza",
        "docena",
        "xyz",
        "kg2",
        "",
        "   ",
        None,
    ],
)
def test_normalize_printed_unit_returns_none_for_unsupported_or_unknown(text):
    """Unsupported units, unrecognised text and missing text map to None."""
    assert normalize_printed_unit(text) is None


@pytest.mark.parametrize(
    ("quantity", "unit_text", "base_unit", "expected"),
    [
        # printed in the food's own base unit
        ("1", "kg", KG, ("1", KG)),
        ("2", "L", L, ("2", L)),
        ("3", "un", UN, ("3", UN)),
        # the printed spelling varies, the result does not
        ("1.5", " Lts. ", L, ("1.5", L)),
        ("0.25", "KG.", KG, ("0.25", KG)),
        # recognised, but reaching the base unit would need a conversion
        ("500", "g", KG, None),
        ("900", "ml", L, None),
        ("33", "cl", L, None),
        # a different dimension than the food's base unit
        ("1", "kg", UN, None),
        ("1", "l", KG, None),
        ("3", "un", L, None),
        # unit text that cannot be used
        ("1", "cucharada", KG, None),
        ("1", "xyz", UN, None),
        ("3", "", UN, None),
        ("3", None, UN, None),
        # no usable quantity
        (None, "kg", KG, None),
        ("0", "kg", KG, None),
        ("-1", "kg", KG, None),
    ],
)
def test_prefill_from_printed(quantity, unit_text, base_unit, expected):
    """A printed quantity is prefilled as-is only when it has a valid amount
    and its unit is exactly the food's base unit; otherwise nothing is."""
    result = prefill_from_printed(
        Decimal(quantity) if quantity is not None else None, unit_text, base_unit
    )

    assert result == (
        (Decimal(expected[0]), expected[1]) if expected is not None else None
    )
