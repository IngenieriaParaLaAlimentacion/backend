"""add food intake tables

Revision ID: b4f1a7c2e590
Revises: 8076ce393029
Create Date: 2026-09-05 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "b4f1a7c2e590"
down_revision: Union[str, Sequence[str], None] = "8076ce393029"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the food intake tables: food_intakes, food_intake_items."""
    op.create_table(
        "food_intakes",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "establishment_id",
            sa.UUID(),
            sa.ForeignKey("establishments.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "responsible_id",
            sa.UUID(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("comments", sa.String(), nullable=True),
        sa.Column(
            "source",
            sa.Enum("manual", "photo", name="foodintakesource"),
            nullable=False,
        ),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True),
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
    )
    op.create_index(
        "ix_food_intakes_establishment_id_received_at",
        "food_intakes",
        ["establishment_id", "received_at"],
    )

    op.create_table(
        "food_intake_items",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "food_intake_id",
            sa.UUID(),
            sa.ForeignKey("food_intakes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "food_id",
            sa.UUID(),
            sa.ForeignKey("foods.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("quantity", sa.Numeric(10, 3), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "quantity > 0", name="ck_food_intake_items_quantity_positive"
        ),
    )
    op.create_index(
        "ix_food_intake_items_food_intake_id", "food_intake_items", ["food_intake_id"]
    )
    op.create_index("ix_food_intake_items_food_id", "food_intake_items", ["food_id"])


def downgrade() -> None:
    """Drop the food intake tables and their enum type."""
    op.drop_index("ix_food_intake_items_food_id", table_name="food_intake_items")
    op.drop_index("ix_food_intake_items_food_intake_id", table_name="food_intake_items")
    op.drop_table("food_intake_items")
    op.drop_index(
        "ix_food_intakes_establishment_id_received_at", table_name="food_intakes"
    )
    op.drop_table("food_intakes")
    sa.Enum(name="foodintakesource").drop(op.get_bind(), checkfirst=True)
