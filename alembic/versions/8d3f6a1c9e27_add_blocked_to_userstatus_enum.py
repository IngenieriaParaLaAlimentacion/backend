"""add blocked to userstatus enum

Revision ID: 8d3f6a1c9e27
Revises: 5b2e8d0c7a41
Create Date: 2026-11-19 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8d3f6a1c9e27"
down_revision: Union[str, Sequence[str], None] = "5b2e8d0c7a41"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add 'blocked' to the userstatus ENUM.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE userstatus ADD VALUE IF NOT EXISTS 'blocked'")


def downgrade() -> None:
    # Postgres does not support removing enum values, so 'blocked' is left
    # in place on downgrade (same limitation as
    # 65b1998cb602_add_withdrawn_to_userestablishmentstatus_.py).
    pass
