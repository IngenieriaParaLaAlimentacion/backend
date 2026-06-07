"""merge geocoding with main

Revision ID: 2fb598be1acf
Revises: 3f8d2a1b9c4e, 5ce092ba2941
Create Date: 2026-06-07 17:21:24.896135

"""

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "2fb598be1acf"
down_revision: Union[str, Sequence[str], None] = ("3f8d2a1b9c4e", "5ce092ba2941")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
