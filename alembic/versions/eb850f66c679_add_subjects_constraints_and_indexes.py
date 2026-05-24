"""add subjects constraints and indexes

Revision ID: eb850f66c679
Revises: 235b18ab1498
Create Date: 2026-05-23 22:42:29.362750

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "eb850f66c679"
down_revision: Union[str, Sequence[str], None] = "235b18ab1498"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_unique_constraint("uq_subjects_dni", "subjects", ["dni"])

    op.create_index("ix_subjects_created_at", "subjects", ["created_at"])

    # Trigram search on name and last_name (supports ILIKE '%term%')
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_index(
        "ix_subjects_name_trgm",
        "subjects",
        ["name"],
        postgresql_using="gin",
        postgresql_ops={"name": "gin_trgm_ops"},
    )
    op.create_index(
        "ix_subjects_last_name_trgm",
        "subjects",
        ["last_name"],
        postgresql_using="gin",
        postgresql_ops={"last_name": "gin_trgm_ops"},
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_subjects_last_name_trgm", table_name="subjects")
    op.drop_index("ix_subjects_name_trgm", table_name="subjects")
    op.drop_index("ix_subjects_created_at", table_name="subjects")
    op.drop_constraint("uq_subjects_dni", "subjects", type_="unique")
