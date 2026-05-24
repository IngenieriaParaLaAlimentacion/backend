"""add unique constraint to subjects dni

Revision ID: eb850f66c679
Revises: 235b18ab1498
Create Date: 2026-05-23 22:42:29.362750

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "eb850f66c679"
down_revision: Union[str, Sequence[str], None] = "235b18ab1498"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_unique_constraint("uq_subjects_dni", "subjects", ["dni"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("uq_subjects_dni", "subjects", type_="unique")
