from app.domain.activity import ActivityType
from app.repositories.activity_repository import ActivityRepository


class TestFeedBranchBuilders:
    def test_every_activity_type_has_a_branch_builder(self):
        """`_build_feed_subquery` iterates `ActivityType` and looks each member
        up in the table, so a type added to the enum but not mapped here would
        raise a KeyError at request time. Fail at test speed instead."""
        assert set(ActivityRepository._FEED_BRANCH_BUILDERS) == set(ActivityType)
