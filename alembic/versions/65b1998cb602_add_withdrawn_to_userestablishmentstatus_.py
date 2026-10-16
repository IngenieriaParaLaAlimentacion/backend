"""add withdrawn to userestablishmentstatus enum

Revision ID: 65b1998cb602
Revises: a1c6b8d47e02
Create Date: 2026-09-19 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "65b1998cb602"
down_revision: Union[str, Sequence[str], None] = "a1c6b8d47e02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add 'withdrawn' to the userestablishmentstatus ENUM.
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE userestablishmentstatus ADD VALUE IF NOT EXISTS 'withdrawn'"
        )


def downgrade() -> None:
    # Postgres does not support removing enum values, so 'withdrawn' is left
    # in place on downgrade (same limitation as
    # 3c300b242b41_add_revoked_to_userestablishmentstatus_.py).
    pass
