"""merge push notification and withdrawn establishment status heads

Revision ID: dc1fd9ec80d0
Revises: e3c13a6cc927, f4b8c2d91e06
Create Date: 2026-09-20 09:28:20.641648

"""

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "dc1fd9ec80d0"
down_revision: Union[str, Sequence[str], None] = ("e3c13a6cc927", "f4b8c2d91e06")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
