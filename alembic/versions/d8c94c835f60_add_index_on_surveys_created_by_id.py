"""add index on surveys.created_by_id

Revision ID: d8c94c835f60
Revises: bd1385cfc0e7
Create Date: 2026-07-28 19:34:55.515366

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d8c94c835f60"
down_revision: Union[str, Sequence[str], None] = "bd1385cfc0e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index(
        "ix_surveys_created_by_id", "surveys", ["created_by_id"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_surveys_created_by_id", table_name="surveys")
