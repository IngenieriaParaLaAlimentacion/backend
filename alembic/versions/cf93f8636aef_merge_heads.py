"""merge heads

Revision ID: cf93f8636aef
Revises: 0e9fed34a9df, c7d4e9a2b8f1
Create Date: 2026-08-16 16:45:58.811543

"""

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "cf93f8636aef"
down_revision: Union[str, Sequence[str], None] = ("0e9fed34a9df", "c7d4e9a2b8f1")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
