from enum import Enum


class PrintedUnit(str, Enum):
    """A unit of measure that can be printed on a receipt line."""

    GRAMOS = "g"
    KILOGRAMOS = "kg"
    MILILITROS = "ml"
    CENTILITROS = "cl"
    LITROS = "l"
    UNIDADES = "unidad"


# Printed spelling (lowercase, no trailing dot) -> the unit it stands for.
_PRINTED_VARIANTS: dict[str, PrintedUnit] = {
    **dict.fromkeys(
        ("g", "gr", "grs", "gramo", "gramos"),
        PrintedUnit.GRAMOS,
    ),
    **dict.fromkeys(
        ("kg", "kgs", "kilo", "kilos", "kilogramo", "kilogramos"),
        PrintedUnit.KILOGRAMOS,
    ),
    **dict.fromkeys(
        ("ml", "cc", "mililitro", "mililitros"),
        PrintedUnit.MILILITROS,
    ),
    **dict.fromkeys(
        ("cl", "centilitro", "centilitros"),
        PrintedUnit.CENTILITROS,
    ),
    **dict.fromkeys(
        ("l", "lt", "lts", "litro", "litros"),
        PrintedUnit.LITROS,
    ),
    **dict.fromkeys(
        ("u", "un", "uni", "unid", "unids", "unidad", "unidades"),
        PrintedUnit.UNIDADES,
    ),
}


def normalize_printed_unit(text: str | None) -> PrintedUnit | None:
    """Map the unit text printed on a receipt to a supported unit.

    Case, surrounding whitespace and a trailing dot are ignored. Returns None
    for missing, blank or unrecognised text (``cucharada``, ``taza``, ...).
    """
    if text is None:
        return None
    return _PRINTED_VARIANTS.get(text.strip().rstrip(".").lower())
