from decimal import Decimal

from app.domain.food_catalog import MeasurementUnit

_QUANTITY_PRECISION = Decimal("0.001")

# Printed unit text (normalized: lowercase, no trailing dot) -> the unit it
# belongs to and the factor that takes a quantity in it to that unit.
_PRINTED_UNITS: dict[str, tuple[MeasurementUnit, Decimal]] = {
    **dict.fromkeys(
        ("kg", "kgs", "kilo", "kilos", "kilogramo", "kilogramos"),
        (MeasurementUnit.KILOGRAMOS, Decimal("1")),
    ),
    **dict.fromkeys(
        ("g", "gr", "grs", "gramo", "gramos"),
        (MeasurementUnit.KILOGRAMOS, Decimal("0.001")),
    ),
    **dict.fromkeys(
        ("l", "lt", "lts", "litro", "litros"),
        (MeasurementUnit.LITROS, Decimal("1")),
    ),
    **dict.fromkeys(
        ("ml", "cc", "mililitro", "mililitros"),
        (MeasurementUnit.LITROS, Decimal("0.001")),
    ),
    **dict.fromkeys(
        ("cl", "centilitro", "centilitros"),
        (MeasurementUnit.LITROS, Decimal("0.01")),
    ),
    **dict.fromkeys(
        ("u", "un", "uni", "unid", "unids", "unidad", "unidades"),
        (MeasurementUnit.UNIDADES, Decimal("1")),
    ),
}


def convert_to_base_unit(
    quantity: Decimal | None,
    unit_text: str | None,
    base_unit: MeasurementUnit,
) -> Decimal | None:
    """Express a receipt-printed quantity in a food's base unit.

    A bare count (a quantity with no unit text) is read as a count of units.
    Returns None when there is no quantity, when the unit text is not
    recognised, when it measures a different dimension than ``base_unit`` (a
    weight printed against a food counted in units, say), or when the result
    rounds to zero.
    """
    if quantity is None:
        return None

    if unit_text is None or not unit_text.strip():
        printed_unit, factor = MeasurementUnit.UNIDADES, Decimal("1")
    else:
        match = _PRINTED_UNITS.get(unit_text.strip().rstrip(".").lower())
        if match is None:
            return None
        printed_unit, factor = match

    if printed_unit is not base_unit:
        return None

    converted = (quantity * factor).quantize(_QUANTITY_PRECISION)
    return converted if converted > 0 else None
