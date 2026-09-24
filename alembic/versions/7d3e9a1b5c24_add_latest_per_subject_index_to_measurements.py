"""Add the latest-per-subject index to measurements."""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "7d3e9a1b5c24"
down_revision: Union[str, Sequence[str], None] = "44511e592f41"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDEX_NAME = "ix_measurements_latest_per_subject"
# Left behind by the deleted migration c9a4b7e2f168 on some databases.
ORPHAN_INDEX_NAME = "ix_measurements_establishment_subject_measured"


def upgrade() -> None:
    """Index measurements in the order the DISTINCT ON queries read them, and
    drop the orphaned index it supersedes."""
    # Column order and sort direction match the ORDER BY of the dashboard's
    # latest-measurement-per-subject subqueries, so Postgres reads rows already
    # ordered instead of sorting them.
    op.create_index(
        INDEX_NAME,
        "measurements",
        [
            "establishment_id",
            "subject_id",
            sa.text("measured_at DESC"),
            sa.text("id DESC"),
        ],
        if_not_exists=True,
    )
    # Its columns (establishment_id, subject_id, measured_at DESC) are a prefix
    # of the new index, so it is redundant and only adds write cost.
    op.drop_index(ORPHAN_INDEX_NAME, table_name="measurements", if_exists=True)


def downgrade() -> None:
    """Drop the latest-per-subject index and restore the orphaned one."""
    op.drop_index(INDEX_NAME, table_name="measurements", if_exists=True)
    op.create_index(
        ORPHAN_INDEX_NAME,
        "measurements",
        ["establishment_id", "subject_id", sa.text("measured_at DESC")],
        if_not_exists=True,
    )
