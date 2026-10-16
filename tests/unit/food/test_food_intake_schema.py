from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.domain.food_intake import FoodIntakeOriginType
from app.schemas.food_intakes.food_intake_schema import FoodIntakeRequest


@pytest.fixture
def valid_intake_payload():
    return {
        "establishment_id": str(uuid4()),
        "occurred_at": datetime(2020, 1, 1, tzinfo=timezone.utc).isoformat(),
        "origin_type": "other",
        "is_recurring": False,
        "items": [{"food_id": str(uuid4()), "quantity": "1.000"}],
    }


@pytest.mark.parametrize("missing", ["origin_type", "is_recurring"])
def test_required_intake_metadata(missing, valid_intake_payload):
    payload = {
        key: value for key, value in valid_intake_payload.items() if key != missing
    }
    with pytest.raises(ValidationError):
        FoodIntakeRequest.model_validate(payload)


@pytest.mark.parametrize("origin", [item.value for item in FoodIntakeOriginType])
def test_every_origin_is_accepted(origin, valid_intake_payload):
    request = FoodIntakeRequest.model_validate(
        {**valid_intake_payload, "origin_type": origin}
    )
    assert request.origin_type.value == origin


def test_unknown_origin_is_rejected(valid_intake_payload):
    with pytest.raises(ValidationError):
        FoodIntakeRequest.model_validate(
            {**valid_intake_payload, "origin_type": "unknown"}
        )


@pytest.mark.parametrize("invalid", ["true", 1, None])
def test_recurrence_requires_boolean(invalid, valid_intake_payload):
    with pytest.raises(ValidationError):
        FoodIntakeRequest.model_validate(
            {**valid_intake_payload, "is_recurring": invalid}
        )


@pytest.mark.parametrize("recurring", [True, False])
def test_recurrence_accepts_only_booleans(recurring, valid_intake_payload):
    request = FoodIntakeRequest.model_validate(
        {**valid_intake_payload, "is_recurring": recurring}
    )
    assert request.is_recurring is recurring
