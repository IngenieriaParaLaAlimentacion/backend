from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.api.v1.params import FoodMovementListingQuery
from app.domain.food_stock import FoodMovementDirection, FoodMovementListingParams
from app.exceptions.domain_exceptions import InvalidDateRangeError

AUGUST = datetime(2026, 8, 1, tzinfo=timezone.utc)
SEPTEMBER = datetime(2026, 9, 1, tzinfo=timezone.utc)


class TestFoodMovementListingQueryToDomain:
    def test_an_empty_query_filters_nothing(self):
        assert FoodMovementListingQuery().to_domain() == FoodMovementListingParams(
            direction=None, occurred_from=None, occurred_to=None, food_id=None
        )

    def test_every_field_is_carried_verbatim(self):
        food_id = uuid4()
        query = FoodMovementListingQuery(
            direction=FoodMovementDirection.OUT,
            occurred_from=AUGUST,
            occurred_to=SEPTEMBER,
            food_id=food_id,
        )

        assert query.to_domain() == FoodMovementListingParams(
            direction=FoodMovementDirection.OUT,
            occurred_from=AUGUST,
            occurred_to=SEPTEMBER,
            food_id=food_id,
        )


class TestFoodMovementListingQueryValidate:
    def test_an_inverted_range_is_refused(self):
        query = FoodMovementListingQuery(occurred_from=SEPTEMBER, occurred_to=AUGUST)

        with pytest.raises(InvalidDateRangeError):
            query.validate()

    @pytest.mark.parametrize(
        ("occurred_from", "occurred_to"),
        [
            (AUGUST, SEPTEMBER),
            (AUGUST, AUGUST),
            (AUGUST, None),
            (None, SEPTEMBER),
            (None, None),
        ],
    )
    def test_a_well_formed_range_passes(self, occurred_from, occurred_to):
        """An equal pair is a valid one-instant window, and a half-open range
        is how a client asks for "everything since" or "everything until"."""
        FoodMovementListingQuery(
            occurred_from=occurred_from, occurred_to=occurred_to
        ).validate()
