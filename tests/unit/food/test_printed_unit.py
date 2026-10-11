import pytest

from app.domain.printed_unit import PrintedUnit, normalize_printed_unit


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
