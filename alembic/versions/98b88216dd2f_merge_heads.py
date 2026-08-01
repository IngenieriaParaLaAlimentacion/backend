"""merge heads

Revision ID: 98b88216dd2f
Revises: 0c49a46a9f0b, c9a4b7e2f168
Create Date: 2026-08-01 14:41:33.630542

"""

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "98b88216dd2f"
down_revision: Union[str, Sequence[str], None] = ("0c49a46a9f0b", "c9a4b7e2f168")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
