"""drop foods grams_per_base_unit

Revision ID: 3f9a7c2d8e41
Revises: 601b0eef15b0
Create Date: 2026-10-25 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "3f9a7c2d8e41"
down_revision: Union[str, Sequence[str], None] = "601b0eef15b0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Drop the temporary per-food gram factor; food_equivalences replaces it."""
    op.drop_constraint("ck_foods_positive_gram_conversion", "foods")
    op.drop_column("foods", "grams_per_base_unit")


def downgrade() -> None:
    """Restore the empty column and its check."""
    op.add_column(
        "foods", sa.Column("grams_per_base_unit", sa.Numeric(12, 3), nullable=True)
    )
    op.create_check_constraint(
        "ck_foods_positive_gram_conversion", "foods", "grams_per_base_unit > 0"
    )
