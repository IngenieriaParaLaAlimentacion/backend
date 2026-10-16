"""Merge food intake and outflow migrations.

Revision ID: e0499c75e66a
Revises: 9f6c2a1b7e40, e6a4f17c902b
"""

from typing import Sequence, Union

revision: str = "e0499c75e66a"
down_revision: Union[str, Sequence[str], None] = (
    "9f6c2a1b7e40",
    "e6a4f17c902b",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Both parent migrations contain the schema changes."""
    pass


def downgrade() -> None:
    """The parent migrations handle their own downgrades."""
    pass
