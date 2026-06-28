"""orphan stub — matches DB head with no local file

Revision ID: 02686ef8c5a8
Revises: 2fb598be1acf, eb850f66c679, d63191bf6620, a4f2c8e1d3b7, c1e7f4a2d9b3
Create Date: 2026-06-20 00:00:00.000000

"""

from typing import Sequence, Union

revision: str = "02686ef8c5a8"
down_revision: Union[str, Sequence[str], None] = (
    "2fb598be1acf",
    "eb850f66c679",
    "d63191bf6620",
    "a4f2c8e1d3b7",
    "c1e7f4a2d9b3",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
