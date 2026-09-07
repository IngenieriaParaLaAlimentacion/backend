"""add food outflow and stock tables

Revision ID: c8e3d5a91f74
Revises: b4f1a7c2e590
Create Date: 2026-09-05 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "c8e3d5a91f74"
down_revision: Union[str, Sequence[str], None] = "9dfe0f10b762"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create food_outflows, food_outflow_items and the food_stock balance."""
    op.create_table(
        "food_outflows",
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
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("comments", sa.String(), nullable=True),
        sa.Column(
            "source",
            sa.Enum("manual", "photo", name="foodoutflowsource"),
            nullable=False,
        ),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_food_outflows_establishment_id_occurred_at",
        "food_outflows",
        ["establishment_id", "occurred_at"],
    )

    op.create_table(
        "food_outflow_items",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "food_outflow_id",
            sa.UUID(),
            sa.ForeignKey("food_outflows.id", ondelete="CASCADE"),
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
            "quantity > 0", name="ck_food_outflow_items_quantity_positive"
        ),
    )
    op.create_index(
        "ix_food_outflow_items_food_outflow_id",
        "food_outflow_items",
        ["food_outflow_id"],
    )
    op.create_index("ix_food_outflow_items_food_id", "food_outflow_items", ["food_id"])

    op.create_table(
        "food_stock",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "establishment_id",
            sa.UUID(),
            sa.ForeignKey("establishments.id", ondelete="RESTRICT"),
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
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        # The upsert that moves the balance conflicts on this constraint, and
        # it doubles as the index for the per-establishment stock listing.
        sa.UniqueConstraint(
            "establishment_id", "food_id", name="uq_food_stock_establishment_id_food_id"
        ),
        sa.CheckConstraint("quantity >= 0", name="ck_food_stock_quantity_non_negative"),
    )


def downgrade() -> None:
    """Drop the stock balance, the outflow tables and their enum type."""
    op.drop_table("food_stock")
    op.drop_index("ix_food_outflow_items_food_id", table_name="food_outflow_items")
    op.drop_index(
        "ix_food_outflow_items_food_outflow_id", table_name="food_outflow_items"
    )
    op.drop_table("food_outflow_items")
    op.drop_index(
        "ix_food_outflows_establishment_id_occurred_at", table_name="food_outflows"
    )
    op.drop_table("food_outflows")
    sa.Enum(name="foodoutflowsource").drop(op.get_bind(), checkfirst=True)
