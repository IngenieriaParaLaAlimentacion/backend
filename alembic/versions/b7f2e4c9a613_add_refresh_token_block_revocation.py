"""Add a block revocation marker to refresh tokens.

Revision ID: b7f2e4c9a613
Revises: 8d3f6a1c9e27
"""

import sqlalchemy as sa

from alembic import op

revision = "b7f2e4c9a613"
down_revision = "8d3f6a1c9e27"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the revocation marker with a default for existing issuers."""
    op.add_column(
        "user_tokens",
        sa.Column(
            "revoked_for_block", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )


def downgrade() -> None:
    """Drop the revocation marker."""
    op.drop_column("user_tokens", "revoked_for_block")
