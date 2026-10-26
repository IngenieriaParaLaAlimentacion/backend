"""add food equivalences

Revision ID: 601b0eef15b0
Revises: c46b13b64867
Create Date: 2026-10-23 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "601b0eef15b0"
down_revision: Union[str, Sequence[str], None] = "c46b13b64867"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create food_equivalences and its enum types."""
    op.create_table(
        "food_equivalences",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "food_id",
            sa.UUID(),
            sa.ForeignKey("foods.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "kind",
            sa.Enum("density_g_ml", "unit_weight_g", name="equivalencekind"),
            nullable=False,
        ),
        sa.Column("value", sa.Numeric(10, 4), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("source_ref", sa.String(), nullable=False),
        sa.Column(
            "match_type",
            sa.Enum("direct", "family", name="equivalencematchtype"),
            nullable=False,
        ),
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
        sa.UniqueConstraint(
            "food_id", "kind", name="uq_food_equivalences_food_id_kind"
        ),
        sa.CheckConstraint("value > 0", name="ck_food_equivalences_value_positive"),
    )


def downgrade() -> None:
    """Drop food_equivalences and its enum types."""
    op.drop_table("food_equivalences")
    sa.Enum(name="equivalencematchtype").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="equivalencekind").drop(op.get_bind(), checkfirst=True)
