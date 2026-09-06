"""add approved/rejected to establishmentrequeststatus enum

Revision ID: 9c55bed7c3d6
Revises: 515e606ec021
Create Date: 2026-08-10 17:18:31.584526

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9c55bed7c3d6"
down_revision: Union[str, Sequence[str], None] = "515e606ec021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add 'approved' and 'rejected' to the establishmentrequeststatus ENUM.
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE establishmentrequeststatus ADD VALUE IF NOT EXISTS 'approved'"
        )
        op.execute(
            "ALTER TYPE establishmentrequeststatus ADD VALUE IF NOT EXISTS 'rejected'"
        )
    # Reconcile drift: the model has declared index=True on `status` since
    # commit e933c51, but no migration ever created the index.
    op.create_index(
        "ix_establishment_requests_status",
        "establishment_requests",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_establishment_requests_status", table_name="establishment_requests"
    )
    # Postgres does not support removing enum values, so 'approved' and
    # 'rejected' are left in place on downgrade (same limitation as
    # 9dfcb864e5a1_feat_add_superadmin_to_userrole_enum.py).
