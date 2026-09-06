"""orphan stub — matches DB head left by the deleted dashboard index migration

The original c9a4b7e2f168_add_dashboard_index_to_measurements.py was applied
to at least one database (creating ix_measurements_establishment_subject_measured
on measurements) and then removed from the codebase without a downgrade.
This stub keeps the revision id resolvable so alembic can walk past it for
any database still stamped at c9a4b7e2f168.

Revision ID: c9a4b7e2f168
Revises: e515758f7b0a
Create Date: 2026-07-30 00:00:00.000000

"""

from typing import Sequence, Union

revision: str = "c9a4b7e2f168"
down_revision: Union[str, Sequence[str], None] = "e515758f7b0a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
