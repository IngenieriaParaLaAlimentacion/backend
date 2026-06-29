"""merge heads

Revision ID: e26ef021fd5e
Revises: 203c9ae7b894, f3a8c2e5d1b9
Create Date: 2026-06-29 14:28:40.089787

"""

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "e26ef021fd5e"
down_revision: Union[str, Sequence[str], None] = ("203c9ae7b894", "f3a8c2e5d1b9")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
