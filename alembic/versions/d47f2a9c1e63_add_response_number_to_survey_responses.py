"""Add configurable response numbers to surveys and their responses.

Backfill and index creation ship in one revision so historical rows are numbered
before the response-number index is created.

Revision ID: d47f2a9c1e63
Revises: 9dfe0f10b762
Create Date: 2026-09-06 10:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d47f2a9c1e63"
down_revision: Union[str, Sequence[str], None] = "9dfe0f10b762"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "surveys",
        sa.Column("requires_response_number", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "survey_responses",
        sa.Column("response_number", sa.Integer(), nullable=True),
    )
    op.execute(
        sa.text(
            """
            UPDATE survey_responses AS r
            SET response_number = numbered.row_number
            FROM (
                SELECT
                    id,
                    row_number() OVER (
                        PARTITION BY survey_id
                        ORDER BY created_at, id
                    ) AS row_number
                FROM survey_responses
            ) AS numbered
            WHERE r.id = numbered.id
            """
        )
    )
    op.add_column(
        "survey_response_edits",
        sa.Column("response_number", sa.Integer(), nullable=True),
    )
    op.execute(
        sa.text(
            """
            UPDATE survey_response_edits AS e
            SET response_number = r.response_number
            FROM survey_responses AS r
            WHERE e.response_id = r.id
            """
        )
    )
    op.create_index(
        "ix_survey_responses_survey_response_number",
        "survey_responses",
        ["survey_id", "response_number"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_survey_responses_survey_response_number",
        table_name="survey_responses",
    )
    op.drop_column("survey_response_edits", "response_number")
    op.drop_column("survey_responses", "response_number")
    op.drop_column("surveys", "requires_response_number")
