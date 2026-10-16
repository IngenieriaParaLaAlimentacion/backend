import pytest

from app.api.v1.params import ActivityListingQuery
from app.domain.activity import ActivityListingParams, ActivityType


class TestActivityListingQueryToDomain:
    def test_omitted_type_produces_none(self):
        """FastAPI yields None (not []) when `type` is absent; to_domain must
        carry that through untouched so the repository expands it to all types."""
        assert ActivityListingQuery().to_domain() == ActivityListingParams(
            activity_types=None
        )

    @pytest.mark.parametrize(
        "activity_types",
        [
            [ActivityType.SUBJECT],
            [ActivityType.FOOD_INTAKE, ActivityType.FOOD_OUTFLOW],
            [ActivityType.SUBJECT, ActivityType.SUBJECT],
        ],
    )
    def test_types_are_carried_verbatim(self, activity_types):
        """to_domain does not dedupe or reorder -- normalization is the
        repository's job, on purpose."""
        params = ActivityListingQuery(activity_types=activity_types).to_domain()

        assert params.activity_types == activity_types
