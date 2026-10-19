from decimal import Decimal
from enum import Enum

from app.domain.food_catalog import MeasurementUnit


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

# Printed units that already are one of the units a food's stock is kept in.
# Grams, millilitres and centilitres are recognised but deliberately absent:
# moving them to a base unit is a conversion, which is not done here.
_STORED_UNIT: dict[PrintedUnit, MeasurementUnit] = {
    PrintedUnit.KILOGRAMOS: MeasurementUnit.KILOGRAMOS,
    PrintedUnit.LITROS: MeasurementUnit.LITROS,
    PrintedUnit.UNIDADES: MeasurementUnit.UNIDADES,
}


def normalize_printed_unit(text: str | None) -> PrintedUnit | None:
    """Map the unit text printed on a receipt to a supported unit.

    Case, surrounding whitespace and a trailing dot are ignored. Returns None
    for missing, blank or unrecognised text (``cucharada``, ``taza``, ...).
    """
    if text is None:
        return None
    return _PRINTED_VARIANTS.get(text.strip().rstrip(".").lower())


def prefill_from_printed(
    quantity: Decimal | None,
    unit_text: str | None,
    base_unit: MeasurementUnit,
) -> tuple[Decimal, MeasurementUnit] | None:
    """Take a receipt-printed quantity as-is when it is in the food's base unit.

    Returns the ``(quantity, unit)`` pair to prefill, or None when there is no
    positive quantity, the unit text is missing or unrecognised, or the printed
    unit is not exactly ``base_unit``. Nothing is converted between units.
    """
    if quantity is None or quantity <= 0:
        return None

    printed_unit = normalize_printed_unit(unit_text)
    if printed_unit is None or _STORED_UNIT.get(printed_unit) is not base_unit:
        return None

    return quantity, base_unit
