"""backfill is_email_verified for pre-existing active users

Revision ID: e515758f7b0a
Revises: e2b1bdeaa6b8
Create Date: 2026-07-24 11:56:10.509676

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "e515758f7b0a"
down_revision: Union[str, Sequence[str], None] = "e2b1bdeaa6b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE users SET is_email_verified = true "
            "WHERE is_email_verified = false "
            "AND status != 'pending_validation'"
        )
    )


def downgrade() -> None:
    pass
