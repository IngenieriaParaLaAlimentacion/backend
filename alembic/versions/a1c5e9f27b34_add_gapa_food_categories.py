"""add gapa food categories

Revision ID: a1c5e9f27b34
Revises: e0499c75e66a
Create Date: 2026-10-10 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "a1c5e9f27b34"
down_revision: Union[str, Sequence[str], None] = "e0499c75e66a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create gapa_food_categories and link foods to it."""
    op.create_table(
        "gapa_food_categories",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.add_column(
        "foods",
        sa.Column(
            "gapa_category_id",
            sa.UUID(),
            sa.ForeignKey("gapa_food_categories.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    op.create_index("ix_foods_gapa_category_id", "foods", ["gapa_category_id"])


def downgrade() -> None:
    """Unlink foods from GAPA groups and drop gapa_food_categories."""
    op.drop_index("ix_foods_gapa_category_id", table_name="foods")
    op.drop_column("foods", "gapa_category_id")
    op.drop_table("gapa_food_categories")
