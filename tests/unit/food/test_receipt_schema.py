from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas.food_intakes.receipt_schema import (
    ProposedFoodLine,
)


def test_proposed_line_requires_an_explicit_review_flag():
    with pytest.raises(ValidationError):
        ProposedFoodLine(description="2 kg arroz")


def test_quantity_rejects_more_than_three_decimals():
    with pytest.raises(ValidationError):
        ProposedFoodLine(
            description="x",
            quantity=Decimal("1.2345"),
            needs_review=False,
        )
