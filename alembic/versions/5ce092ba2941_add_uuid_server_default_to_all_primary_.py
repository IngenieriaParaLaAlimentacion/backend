"""add uuid server default to all primary key ids

Revision ID: 5ce092ba2941
Revises: eb850f66c679
Create Date: 2026-05-24 21:37:12.559362

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5ce092ba2941"
down_revision: Union[str, None] = "eb850f66c679"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLES = [
    "establishments",
    "subjects",
    "users",
    "measurements",
    "user_passwords",
    "user_tokens",
    "subject_events",
]


def upgrade() -> None:
    """Add gen_random_uuid() as server-side default for all UUID primary keys."""
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    for table in _TABLES:
        op.alter_column(
            table,
            "id",
            server_default=sa.text("gen_random_uuid()"),
        )


def downgrade() -> None:
    """Remove server-side default from all UUID primary keys."""
    for table in _TABLES:
        op.alter_column(table, "id", server_default=None)
