"""add locality, description, contact_phone to users

Revision ID: f3a8c2e5d1b9
Revises: c1e7f4a2d9b3
Create Date: 2026-06-28 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "f3a8c2e5d1b9"
down_revision: Union[str, Sequence[str], None] = "c1e7f4a2d9b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("locality", sa.String(), nullable=True))
    op.add_column("users", sa.Column("description", sa.String(), nullable=True))
    op.add_column("users", sa.Column("contact_phone", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "contact_phone")
    op.drop_column("users", "description")
    op.drop_column("users", "locality")
