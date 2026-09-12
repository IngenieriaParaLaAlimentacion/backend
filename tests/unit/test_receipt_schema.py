import uuid
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas.food_intakes.receipt_schema import (
    ProposedFoodLine,
    ReceiptProposalResponse,
)


def test_empty_proposal_defaults_to_no_lines_and_no_message():
    proposal = ReceiptProposalResponse(
        establishment_id=uuid.uuid4(), photo_key="food-intake-receipts/e/f.jpg"
    )

    assert proposal.lines == []
    assert proposal.message is None


def test_proposal_requires_a_photo_key():
    with pytest.raises(ValidationError):
        ReceiptProposalResponse(establishment_id=uuid.uuid4())


def test_proposed_line_requires_an_explicit_review_flag():
    with pytest.raises(ValidationError):
        ProposedFoodLine(description="2 kg arroz")


def test_unmatched_line_keeps_food_and_quantity_null():
    line = ProposedFoodLine(description="algo ilegible", needs_review=True)

    assert line.food is None
    assert line.quantity is None
    assert line.unit is None


def test_matched_line_carries_the_catalog_ref_and_quantity():
    food_id = uuid.uuid4()
    line = ProposedFoodLine(
        description="ARROZ LARGO FINO 1KG",
        food={"id": food_id, "name": "Arroz"},
        quantity=Decimal("2.000"),
        unit="kilogramos",
        needs_review=False,
    )

    assert line.food.id == food_id
    assert line.quantity == Decimal("2.000")
    assert line.unit.value == "kilogramos"


def test_quantity_rejects_more_than_three_decimals():
    with pytest.raises(ValidationError):
        ProposedFoodLine(
            description="x",
            quantity=Decimal("1.2345"),
            needs_review=False,
        )
