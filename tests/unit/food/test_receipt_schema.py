from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas.food_intakes.receipt_schema import (
    ProposedFoodLine,
)


def test_quantity_rejects_more_than_three_decimals():
    with pytest.raises(ValidationError):
        ProposedFoodLine(description="x", quantity=Decimal("1.2345"))
