"""add composite index on measurements for the establishment dashboard

Revision ID: c9a4b7e2f168
Revises: e515758f7b0a
Create Date: 2026-07-26 10:00:00.000000

Postgres does not index foreign keys automatically, so measurements had no
index on establishment_id at all. The dashboard resolves each subject's latest
measurement at an establishment with a DISTINCT ON over exactly these three
columns in this order; without the index every dashboard load is a sequential
scan of the whole measurements table.
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "c9a4b7e2f168"
down_revision: Union[str, Sequence[str], None] = "e515758f7b0a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDEX_NAME = "ix_measurements_establishment_subject_measured"


def upgrade() -> None:
    op.create_index(
        INDEX_NAME,
        "measurements",
        ["establishment_id", "subject_id", sa.text("measured_at DESC")],
    )


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name="measurements")
