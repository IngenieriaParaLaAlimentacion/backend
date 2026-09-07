"""merge food intake and food search heads

Revision ID: 9dfe0f10b762
Revises: 4099691d9bcd, b4f1a7c2e590
Create Date: 2026-09-07 09:12:09.208792

"""

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "9dfe0f10b762"
down_revision: Union[str, Sequence[str], None] = ("4099691d9bcd", "b4f1a7c2e590")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
