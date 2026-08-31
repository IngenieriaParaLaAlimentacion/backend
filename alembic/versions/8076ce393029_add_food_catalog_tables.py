"""add food catalog tables

Revision ID: 8076ce393029
Revises: 3c300b242b41
Create Date: 2026-08-30 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "8076ce393029"
down_revision: Union[str, Sequence[str], None] = "3c300b242b41"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the food catalog tables: food_categories, foods, nutrients,
    food_nutrient_values."""
    op.create_table(
        "food_categories",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("sara2_group_number", sa.SmallInteger(), nullable=False),
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
        sa.UniqueConstraint("sara2_group_number"),
    )

    op.create_table(
        "foods",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column(
            "category_id",
            sa.UUID(),
            sa.ForeignKey("food_categories.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "base_unit",
            sa.Enum("unidades", "kilogramos", "litros", name="measurementunit"),
            nullable=False,
        ),
        sa.Column(
            "is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column("source_page", sa.SmallInteger(), nullable=True),
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
    op.create_index("ix_foods_category_id", "foods", ["category_id"])

    op.create_table(
        "nutrients",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("unit", sa.String(), nullable=False),
        sa.Column(
            "group",
            sa.Enum(
                "macronutrient",
                "vitamin",
                "mineral",
                "fatty_acid",
                name="nutrientgroup",
            ),
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
        sa.UniqueConstraint("code"),
    )

    op.create_table(
        "food_nutrient_values",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "food_id",
            sa.UUID(),
            sa.ForeignKey("foods.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "nutrient_id",
            sa.UUID(),
            sa.ForeignKey("nutrients.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("amount_per_100g", sa.Numeric(10, 4), nullable=False),
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
            "food_id", "nutrient_id", name="uq_food_nutrient_values_food_id_nutrient_id"
        ),
    )


def downgrade() -> None:
    """Drop the food catalog tables and their enum types."""
    op.drop_table("food_nutrient_values")
    op.drop_table("nutrients")
    sa.Enum(name="nutrientgroup").drop(op.get_bind(), checkfirst=True)
    op.drop_index("ix_foods_category_id", table_name="foods")
    op.drop_table("foods")
    sa.Enum(name="measurementunit").drop(op.get_bind(), checkfirst=True)
    op.drop_table("food_categories")
