from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

_QUANTITY_PRECISION = Decimal("0.001")

# The largest value that fits ``max_digits=10, decimal_places=3`` on a
# proposed line, so a parsed quantity can always be placed on one.
_MAX_QUANTITY = Decimal("9999999.999")


def parse_printed_quantity(value: Any) -> Decimal | None:
    """Parse a quantity read from a receipt into a positive ``Decimal``.

    Accepts numbers and numeric text with either ``,`` or ``.`` as the decimal
    separator (``"1,5"`` and ``"1.5"`` are the same). The result is rounded to
    three decimals, half up.

    Returns None for a missing value, text that is not a single plain number
    (``"1 kg"``, ``"1.000,5"``), a non-finite value, a value that is zero or
    negative (also after rounding), or one too large to store.
    """
    if value is None or isinstance(value, bool):
        return None

    try:
        number = Decimal(str(value).strip().replace(",", "."))
    except InvalidOperation:
        return None

    if not number.is_finite() or number <= 0 or number > _MAX_QUANTITY:
        return None

    rounded = number.quantize(_QUANTITY_PRECISION, rounding=ROUND_HALF_UP)
    return rounded if rounded > 0 else None
