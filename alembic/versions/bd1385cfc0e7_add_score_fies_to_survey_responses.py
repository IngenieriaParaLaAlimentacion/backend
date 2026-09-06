"""add score_fies to survey_responses

Revision ID: bd1385cfc0e7
Revises: 76b6f29d84d0
Create Date: 2026-07-25 12:27:03.255122

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "bd1385cfc0e7"
down_revision: Union[str, Sequence[str], None] = "76b6f29d84d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "survey_responses", sa.Column("score_fies", sa.Integer(), nullable=True)
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("survey_responses", "score_fies")
