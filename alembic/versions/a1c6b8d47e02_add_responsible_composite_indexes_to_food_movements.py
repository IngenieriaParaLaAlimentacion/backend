"""add responsible composite indexes to food movements

Revision ID: a1c6b8d47e02
Revises: d47f2a9c1e63
Create Date: 2026-09-13 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op

"""
add (responsible_id, timestamp) composite indexes to the food-movement tables

GET /users/me/activity filters each branch by its ownership column and orders
the merged feed by the movement's own event time. For food movements that is
`responsible_id` + `received_at` / `occurred_at`, and neither table had an
index leading with `responsible_id` -- the existing ones lead with
`establishment_id`, which the feed never filters on.

Composite instead of a standalone index on the timestamp: the query is always
equality on the responsible plus ordering on the timestamp, so the composite
covers both in one pass. Plain ascending btree: PostgreSQL scans a btree
backwards for `ORDER BY ... DESC` at the same cost, so no DESC operator class
is needed."""

# revision identifiers, used by Alembic.
revision: str = "a1c6b8d47e02"
down_revision: Union[str, Sequence[str], None] = "d47f2a9c1e63"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index(
        "ix_food_intakes_responsible_id_received_at",
        "food_intakes",
        ["responsible_id", "received_at"],
        unique=False,
    )
    op.create_index(
        "ix_food_outflows_responsible_id_occurred_at",
        "food_outflows",
        ["responsible_id", "occurred_at"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_food_outflows_responsible_id_occurred_at", table_name="food_outflows"
    )
    op.drop_index(
        "ix_food_intakes_responsible_id_received_at", table_name="food_intakes"
    )
