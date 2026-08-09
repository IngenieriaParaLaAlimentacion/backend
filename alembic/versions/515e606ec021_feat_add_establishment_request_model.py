"""add establishment_requests table

Revision ID: 515e606ec021
Revises: 98b88216dd2f
Create Date: 2026-08-09 15:56:43.778873

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "515e606ec021"
down_revision: Union[str, Sequence[str], None] = "98b88216dd2f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the establishment_requests notification table."""
    op.create_table(
        "establishment_requests",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "user_id",
            sa.UUID(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("formatted_address", sa.String(), nullable=True),
        sa.Column("city", sa.String(), nullable=True),
        sa.Column("province", sa.String(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("pending", name="establishmentrequeststatus"),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_establishment_requests_user_id",
        "establishment_requests",
        ["user_id"],
    )


def downgrade() -> None:
    """Drop the establishment_requests table and its status enum."""
    op.drop_index(
        "ix_establishment_requests_user_id", table_name="establishment_requests"
    )
    op.drop_table("establishment_requests")
    sa.Enum(name="establishmentrequeststatus").drop(op.get_bind(), checkfirst=True)
