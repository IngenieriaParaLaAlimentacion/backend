"""Add a disposition category to food outflows."""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "9f6c2a1b7e40"
down_revision: Union[str, Sequence[str], None] = "7d3e9a1b5c24"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CATEGORY = postgresql.ENUM(
    "family_delivery",
    "kitchen",
    "discard",
    "other",
    name="foodoutflowcategory",
    create_type=False,
)


def upgrade() -> None:
    """Classify existing outflows as other and require a category on every row."""
    CATEGORY.create(op.get_bind(), checkfirst=True)
    op.add_column("food_outflows", sa.Column("category", CATEGORY, nullable=True))
    op.execute("UPDATE food_outflows SET category = 'other' WHERE category IS NULL")
    op.alter_column(
        "food_outflows",
        "category",
        existing_type=CATEGORY,
        nullable=False,
        server_default=sa.text("'other'::foodoutflowcategory"),
    )


def downgrade() -> None:
    """Remove the category column and its PostgreSQL enum."""
    op.drop_column("food_outflows", "category")
    CATEGORY.drop(op.get_bind(), checkfirst=True)
