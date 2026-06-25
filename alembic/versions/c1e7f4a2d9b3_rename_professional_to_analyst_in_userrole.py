"""rename professional to analyst and establishment_manager to field_worker
in userrole enum

Revision ID: c1e7f4a2d9b3
Revises: a4f2c8e1d3b7
Create Date: 2026-06-25 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op

revision: str = "c1e7f4a2d9b3"
down_revision: Union[str, Sequence[str], None] = "a4f2c8e1d3b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE userrole RENAME VALUE 'professional' TO 'analyst'")
    op.execute(
        "ALTER TYPE userrole RENAME VALUE 'establishment_manager' TO 'field_worker'"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TYPE userrole RENAME VALUE 'field_worker' TO 'establishment_manager'"
    )
    op.execute("ALTER TYPE userrole RENAME VALUE 'analyst' TO 'professional'")
