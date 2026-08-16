"""add reviewed_by to establishment_requests

Revision ID: 0e9fed34a9df
Revises: 9c55bed7c3d6
Create Date: 2026-08-11 15:51:55.775693

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0e9fed34a9df"
down_revision: Union[str, Sequence[str], None] = "9c55bed7c3d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Track which admin reviewed (approved/rejected) a request."""
    op.add_column(
        "establishment_requests",
        sa.Column(
            "reviewed_by",
            sa.UUID(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("establishment_requests", "reviewed_by")
