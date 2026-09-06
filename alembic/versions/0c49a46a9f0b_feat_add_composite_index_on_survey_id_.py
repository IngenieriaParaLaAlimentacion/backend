"""feat: add composite index on (survey_id, event_at)

Revision ID: 0c49a46a9f0b
Revises: d8c94c835f60
Create Date: 2026-07-28 19:43:18.741485

"""

from typing import Sequence, Union

from alembic import op

"""
add composite index on survey_responses(survey_id, event_at)

Composite instead of a standalone index on event_at, since the most
frequent query pattern (list_by_survey / dashboard) always filters by
survey_id and orders by event_at DESC. The composite covers equality +
ordering in one pass, avoiding an extra sort.

The global filter in /analytics/survey-response-summary (no survey_id)
doesn't benefit from this index and is left on seq scan for now; not
adding a standalone index until there's real evidence it's needed at
production volume."""

# revision identifiers, used by Alembic.
revision: str = "0c49a46a9f0b"
down_revision: Union[str, Sequence[str], None] = "d8c94c835f60"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index(
        "ix_survey_responses_survey_id_event_at",
        "survey_responses",
        ["survey_id", "event_at"],
        unique=False,
    )
    # ### end Alembic commands ###


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_survey_responses_survey_id_event_at", table_name="survey_responses"
    )
    # ### end Alembic commands ###
