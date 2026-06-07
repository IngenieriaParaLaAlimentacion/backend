"""feat: add geocoding fields to establishments

Revision ID: 3f8d2a1b9c4e
Revises: d63191bf6620
Create Date: 2026-06-07 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "3f8d2a1b9c4e"
down_revision: Union[str, None] = "d63191bf6620"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("establishments", "address", new_column_name="formatted_address")
    op.add_column("establishments", sa.Column("latitude", sa.Float(), nullable=False))
    op.add_column("establishments", sa.Column("longitude", sa.Float(), nullable=False))
    op.add_column("establishments", sa.Column("place_id", sa.String(), nullable=False))
    op.add_column("establishments", sa.Column("city", sa.String(), nullable=False))
    op.add_column("establishments", sa.Column("province", sa.String(), nullable=False))


def downgrade() -> None:
    op.drop_column("establishments", "province")
    op.drop_column("establishments", "city")
    op.drop_column("establishments", "place_id")
    op.drop_column("establishments", "longitude")
    op.drop_column("establishments", "latitude")
    op.alter_column("establishments", "formatted_address", new_column_name="address")
