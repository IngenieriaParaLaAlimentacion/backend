"""add instrument_type to surveys

Revision ID: 76b6f29d84d0
Revises: e2b1bdeaa6b8
Create Date: 2026-07-25 11:08:16.354583

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "76b6f29d84d0"
down_revision: Union[str, Sequence[str], None] = "e2b1bdeaa6b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

survey_instrument_type = sa.Enum("custom", "fies", name="surveyinstrumenttype")


def upgrade() -> None:
    """Upgrade schema."""
    survey_instrument_type.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "surveys",
        sa.Column(
            "instrument_type",
            survey_instrument_type,
            nullable=False,
            server_default="custom",
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("surveys", "instrument_type")
    survey_instrument_type.drop(op.get_bind(), checkfirst=True)
