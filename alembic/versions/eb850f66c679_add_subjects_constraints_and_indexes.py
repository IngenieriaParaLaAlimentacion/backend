"""add subjects constraints, indexes, event log and establishments created_at index

Revision ID: eb850f66c679
Revises: 235b18ab1498
Create Date: 2026-05-23 22:42:29.362750

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

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
    op.create_index("ix_establishments_created_at", "establishments", ["created_at"])

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

    op.create_table(
        "subject_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "event_type",
            sa.Enum("SUBJECT_CREATED", "SUBJECT_UPDATED", name="subjecteventtype"),
            nullable=False,
        ),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("payload", postgresql.JSONB(), nullable=True),
        sa.ForeignKeyConstraint(["subject_id"], ["subjects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_subject_events_subject_id", "subject_events", ["subject_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_subject_events_subject_id", table_name="subject_events")
    op.drop_table("subject_events")
    sa.Enum(name="subjecteventtype").drop(op.get_bind())

    op.drop_index("ix_subjects_last_name_trgm", table_name="subjects")
    op.drop_index("ix_subjects_name_trgm", table_name="subjects")
    op.drop_index("ix_establishments_created_at", table_name="establishments")
    op.drop_index("ix_subjects_created_at", table_name="subjects")
    op.drop_constraint("uq_subjects_dni", "subjects", type_="unique")
