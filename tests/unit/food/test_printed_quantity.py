from decimal import Decimal

import pytest

from app.domain.printed_quantity import parse_printed_quantity


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        # plain numbers, as the extractor returns them
        (1, "1"),
        (500, "500"),
        (1.5, "1.5"),
        # text, with either decimal separator
        ("1", "1"),
        ("1.5", "1.5"),
        ("1,5", "1.5"),
        (" 2,25 ", "2.25"),
        # more than three decimals are rounded half up
        ("1.2344", "1.234"),
        ("1.2345", "1.235"),
        ("0.0005", "0.001"),
        # the largest value a proposed line can hold
        ("9999999.999", "9999999.999"),
    ],
)
def test_parse_printed_quantity_accepts_valid_quantities(value, expected):
    """A valid quantity is parsed to a Decimal of at most three decimals."""
    assert parse_printed_quantity(value) == Decimal(expected)


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "abc",
        "1 kg",
        # ambiguous grouping: not read as a number
        "1.000,5",
        "1,000.5",
        # not finite
        "nan",
        float("inf"),
        # not a positive amount
        0,
        "0",
        -1,
        "0.0004",
        True,
        # too large to store, e.g. a barcode or a price read as the quantity
        "10000000",
        "7791234567890",
        1e30,
    ],
)
def test_parse_printed_quantity_returns_none_for_unusable_values(value):
    """Missing, non-numeric, non-finite, non-positive and oversized values
    all map to None."""
    assert parse_printed_quantity(value) is None
