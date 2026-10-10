"""Add origin type and recurrence to food intakes.

Revision ID: e6a4f17c902b
Revises: 7d3e9a1b5c24
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "e6a4f17c902b"
down_revision: Union[str, Sequence[str], None] = "7d3e9a1b5c24"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

origin_type = postgresql.ENUM(
    "national_government",
    "provincial_government",
    "municipal_government",
    "private_company",
    "foundation",
    "social_organization",
    "church",
    "other",
    name="foodintakeorigintype",
    create_type=False,
)


def upgrade() -> None:
    """Add non-null intake origin and recurrence, backfilling existing rows."""
    origin_type.create(op.get_bind(), checkfirst=False)
    op.add_column(
        "food_intakes",
        sa.Column("origin_type", origin_type, nullable=True),
    )
    op.add_column(
        "food_intakes",
        sa.Column("is_recurring", sa.Boolean(), nullable=True),
    )
    op.execute(
        "UPDATE food_intakes "
        "SET origin_type = 'other', is_recurring = false "
        "WHERE origin_type IS NULL OR is_recurring IS NULL"
    )
    op.alter_column("food_intakes", "origin_type", nullable=False)
    op.alter_column("food_intakes", "is_recurring", nullable=False)


def downgrade() -> None:
    """Remove intake origin and recurrence and their PostgreSQL enum."""
    op.drop_column("food_intakes", "is_recurring")
    op.drop_column("food_intakes", "origin_type")
    origin_type.drop(op.get_bind(), checkfirst=False)
