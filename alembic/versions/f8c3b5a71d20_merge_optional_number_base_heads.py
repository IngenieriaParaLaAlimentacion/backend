"""Merge the survey response-number and food feature heads.

Revision ID: f8c3b5a71d20
Revises: d47f2a9c1e63, 9dfe0f10b762
"""

from typing import Sequence, Union

revision: str = "f8c3b5a71d20"
down_revision: Union[str, Sequence[str], None] = (
    "d47f2a9c1e63",
    "9dfe0f10b762",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Merge the existing heads without changing the schema."""


def downgrade() -> None:
    """Split the migration graph back into its prior heads."""
