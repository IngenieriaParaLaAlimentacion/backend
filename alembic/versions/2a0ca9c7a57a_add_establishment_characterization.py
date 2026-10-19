"""add establishment characterization

Revision ID: 2a0ca9c7a57a
Revises: a1c5e9f27b34
Create Date: 2026-10-18 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "2a0ca9c7a57a"
down_revision: Union[str, Sequence[str], None] = "a1c5e9f27b34"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add the characterization profile to establishments and their requests."""
    op.add_column(
        "establishments",
        sa.Column(
            "characterization", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
    )
    op.add_column(
        "establishment_requests",
        sa.Column(
            "characterization", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
    )


def downgrade() -> None:
    """Drop the characterization profile."""
    op.drop_column("establishment_requests", "characterization")
    op.drop_column("establishments", "characterization")
