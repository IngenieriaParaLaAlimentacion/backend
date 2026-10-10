"""Validate food outflow disposition and legacy request compatibility."""

import uuid
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.domain.food_outflow import FoodOutflowCategory
from app.schemas.food_outflows.food_outflow_schema import FoodOutflowRequest


def _body(**overrides):
    return {
        "establishment_id": uuid.uuid4(),
        "occurred_at": datetime(2026, 9, 1, tzinfo=timezone.utc),
        "items": [{"food_id": uuid.uuid4(), "quantity": "1"}],
        **overrides,
    }


@pytest.mark.parametrize("category", list(FoodOutflowCategory))
def test_accepts_each_category(category):
    assert FoodOutflowRequest.model_validate(_body(category=category)).category == category


def test_missing_category_temporarily_means_other():
    request = FoodOutflowRequest.model_validate(_body(comments="Legacy detail"))
    assert request.category is FoodOutflowCategory.OTHER
    assert request.comments == "Legacy detail"


@pytest.mark.parametrize("comments", [None, "", "unexpected"])
def test_non_other_rejects_any_present_comments_key(comments):
    with pytest.raises(ValidationError):
        FoodOutflowRequest.model_validate(_body(category="kitchen", comments=comments))


def test_non_other_accepts_omitted_comments_key():
    request = FoodOutflowRequest.model_validate(_body(category="discard"))
    assert request.comments is None


@pytest.mark.parametrize("category", [None, "unknown"])
def test_rejects_invalid_category(category):
    with pytest.raises(ValidationError):
        FoodOutflowRequest.model_validate(_body(category=category))


def test_other_allows_optional_comments():
    request = FoodOutflowRequest.model_validate(
        _body(category="other", comments="Community event")
    )
    assert request.comments == "Community event"
