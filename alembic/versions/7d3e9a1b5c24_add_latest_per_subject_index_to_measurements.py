"""Add the latest-per-subject index to measurements."""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "7d3e9a1b5c24"
down_revision: Union[str, Sequence[str], None] = "44511e592f41"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDEX_NAME = "ix_measurements_latest_per_subject"


def upgrade() -> None:
    """Index measurements in the order the DISTINCT ON queries read them."""
    # Column order and sort direction match the ORDER BY of the dashboard's
    # latest-measurement-per-subject subqueries, so Postgres reads rows already
    # ordered instead of sorting them. A new name is used on purpose: some
    # databases still hold an orphaned index from a deleted migration
    # (see c9a4b7e2f168), whose definition is unknown.
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


def downgrade() -> None:
    """Drop the latest-per-subject index."""
    op.drop_index(INDEX_NAME, table_name="measurements", if_exists=True)
