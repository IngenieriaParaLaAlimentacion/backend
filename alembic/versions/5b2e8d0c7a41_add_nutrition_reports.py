"""add nutrition reports

Revision ID: 5b2e8d0c7a41
Revises: 3f9a7c2d8e41
Create Date: 2026-10-18 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "5b2e8d0c7a41"
down_revision: Union[str, Sequence[str], None] = "3f9a7c2d8e41"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

summary_status = postgresql.ENUM(
    "generated",
    "unavailable",
    "not_applicable",
    name="nutritionreportsummarystatus",
    create_type=False,
)


def upgrade() -> None:
    """Create nutrition_reports and its summary status enum."""
    summary_status.create(op.get_bind(), checkfirst=False)
    op.create_table(
        "nutrition_reports",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("establishment_id", sa.UUID(), nullable=False),
        sa.Column("month", sa.Date(), nullable=False),
        sa.Column("has_data", sa.Boolean(), nullable=False),
        sa.Column("analysis", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("reference_profile", sa.String(), nullable=False),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("summary_status", summary_status, nullable=False),
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
        sa.ForeignKeyConstraint(
            ["establishment_id"], ["establishments.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "establishment_id",
            "month",
            name="uq_nutrition_reports_establishment_id_month",
        ),
        sa.CheckConstraint(
            "EXTRACT(day FROM month) = 1",
            name="ck_nutrition_reports_month_is_first_day",
        ),
        sa.CheckConstraint(
            "(summary_status = 'generated') = (summary IS NOT NULL)",
            name="ck_nutrition_reports_summary_matches_status",
        ),
        sa.CheckConstraint(
            "has_data = (summary_status <> 'not_applicable')",
            name="ck_nutrition_reports_has_data_matches_summary_status",
        ),
    )


def downgrade() -> None:
    """Drop nutrition_reports and its summary status enum."""
    op.drop_table("nutrition_reports")
    summary_status.drop(op.get_bind(), checkfirst=False)
