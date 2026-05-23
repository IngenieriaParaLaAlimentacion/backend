"""feat: add superadmin to userrole enum

Revision ID: 9dfcb864e5a1
Revises: 235b18ab1498
Create Date: 2026-05-23 16:41:22.773375

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '9dfcb864e5a1'
down_revision: Union[str, Sequence[str], None] = '235b18ab1498'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add 'superadmin' to the userrole ENUM
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'superadmin'")


def downgrade() -> None:
    """Downgrade schema."""
    pass