"""add user block events

Revision ID: c4a9e1d7b3f5
Revises: 8d3f6a1c9e27
Create Date: 2026-11-19 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "c4a9e1d7b3f5"
down_revision: Union[str, Sequence[str], None] = "8d3f6a1c9e27"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

event_type = postgresql.ENUM(
    "blocked",
    "unblocked",
    name="userblockeventtype",
    create_type=False,
)


def upgrade() -> None:
    """Create user_block_events and its event type enum."""
    event_type.create(op.get_bind(), checkfirst=False)
    op.create_table(
        "user_block_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("actor_id", sa.UUID(), nullable=False),
        sa.Column("event_type", event_type, nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_block_events_user_id", "user_block_events", ["user_id"])


def downgrade() -> None:
    """Drop user_block_events and its event type enum."""
    op.drop_index("ix_user_block_events_user_id", table_name="user_block_events")
    op.drop_table("user_block_events")
    event_type.drop(op.get_bind(), checkfirst=False)
