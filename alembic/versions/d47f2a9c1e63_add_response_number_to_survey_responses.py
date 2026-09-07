"""Add configurable response numbers to surveys and their responses.

Historical rows remain unnumbered because response numbers are optional references
copied from paper forms.

Revision ID: d47f2a9c1e63
Revises: c8e3d5a91f74
Create Date: 2026-09-06 10:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d47f2a9c1e63"
down_revision: Union[str, Sequence[str], None] = "c8e3d5a91f74"
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
    op.add_column(
        "survey_response_edits",
        sa.Column("response_number", sa.Integer(), nullable=True),
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
