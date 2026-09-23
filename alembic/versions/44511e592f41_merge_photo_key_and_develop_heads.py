"""merge photo_key and develop heads

Revision ID: 44511e592f41
Revises: dc1fd9ec80d0, ec7aacdaf1ae
Create Date: 2026-09-23 11:08:45.512295

"""

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "44511e592f41"
down_revision: Union[str, Sequence[str], None] = ("dc1fd9ec80d0", "ec7aacdaf1ae")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
