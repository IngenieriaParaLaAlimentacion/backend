"""add revoked to userestablishmentstatus enum

Revision ID: 3c300b242b41
Revises: cf93f8636aef
Create Date: 2026-08-22 19:22:46.897274

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3c300b242b41"
down_revision: Union[str, Sequence[str], None] = "cf93f8636aef"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add 'revoked' to the userestablishmentstatus ENUM.
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE userestablishmentstatus ADD VALUE IF NOT EXISTS 'revoked'"
        )


def downgrade() -> None:
    # Postgres does not support removing enum values, so 'revoked' is left
    # in place on downgrade (same limitation as
    # 9c55bed7c3d6_add_approved_rejected_to_.py).
    pass
