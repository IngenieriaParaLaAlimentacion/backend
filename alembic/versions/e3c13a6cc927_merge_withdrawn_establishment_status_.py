"""merge withdrawn establishment status and food intake rename heads

Revision ID: e3c13a6cc927
Revises: 65b1998cb602, f3b9e1a7c204
Create Date: 2026-09-19 22:13:32.500210

"""

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "e3c13a6cc927"
down_revision: Union[str, Sequence[str], None] = ("65b1998cb602", "f3b9e1a7c204")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
