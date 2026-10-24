"""Add optional observation text to measurements.

Revision ID: a8c4f6d2e901
Revises: 2a0ca9c7a57a
"""

import sqlalchemy as sa

from alembic import op

revision = "a8c4f6d2e901"
down_revision = "2a0ca9c7a57a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add a nullable observation without changing existing measurements."""
    op.add_column("measurements", sa.Column("observation", sa.Text(), nullable=True))


def downgrade() -> None:
    """Remove measurement observations."""
    op.drop_column("measurements", "observation")
