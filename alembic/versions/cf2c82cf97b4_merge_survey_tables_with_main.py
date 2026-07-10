"""merge survey tables with main

Revision ID: cf2c82cf97b4
Revises: b7e3c9a1f2d4, e26ef021fd5e
Create Date: 2026-07-10 16:27:07.074436

"""

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "cf2c82cf97b4"
down_revision: Union[str, Sequence[str], None] = ("b7e3c9a1f2d4", "e26ef021fd5e")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
