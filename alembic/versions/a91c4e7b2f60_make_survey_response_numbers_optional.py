"""Make survey response numbers optional.

Revision ID: a91c4e7b2f60
Revises: f8c3b5a71d20
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "a91c4e7b2f60"
down_revision: Union[str, Sequence[str], None] = "f8c3b5a71d20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add survey configuration and permit numberless snapshots."""
    op.add_column(
        "surveys",
        sa.Column("requires_response_number", sa.Boolean(), nullable=True),
    )
    op.alter_column(
        "survey_responses",
        "response_number",
        existing_type=sa.Integer(),
        nullable=True,
    )
    op.alter_column(
        "survey_response_edits",
        "response_number",
        existing_type=sa.Integer(),
        nullable=True,
    )


def downgrade() -> None:
    """Restore global requiredness, filling only missing number snapshots."""
    op.execute(
        sa.text(
            """
            UPDATE survey_responses AS response
            SET response_number = numbered.row_number
            FROM (
                SELECT id,
                       row_number() OVER (
                           PARTITION BY survey_id ORDER BY created_at, id
                       ) AS row_number
                FROM survey_responses
            ) AS numbered
            WHERE response.id = numbered.id
              AND response.response_number IS NULL
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE survey_response_edits AS edit
            SET response_number = response.response_number
            FROM survey_responses AS response
            WHERE edit.response_id = response.id
              AND edit.response_number IS NULL
            """
        )
    )
    op.alter_column(
        "survey_response_edits",
        "response_number",
        existing_type=sa.Integer(),
        nullable=False,
    )
    op.alter_column(
        "survey_responses",
        "response_number",
        existing_type=sa.Integer(),
        nullable=False,
    )
    op.drop_column("surveys", "requires_response_number")
