"""merge recipe recommendations and develop migrations

Revision ID: c46b13b64867
Revises: b7d170a4e901, b7d2e5f1a3c8
Create Date: 2026-10-24 17:13:02.699292

"""

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "c46b13b64867"
down_revision: Union[str, Sequence[str], None] = ("b7d170a4e901", "b7d2e5f1a3c8")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
