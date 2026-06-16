"""add idempotency_key and bmi to measurements, add measurement_alerts

Revision ID: a4f2c8e1d3b7
Revises: 2fb598be1acf
Create Date: 2026-06-15 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "a4f2c8e1d3b7"
down_revision: Union[str, None] = "2fb598be1acf"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "measurements",
        sa.Column("idempotency_key", postgresql.UUID(as_uuid=True), nullable=False),
    )
    op.create_unique_constraint(
        "uq_measurements_idempotency_key", "measurements", ["idempotency_key"]
    )
    op.add_column(
        "measurements",
        sa.Column("bmi", sa.Float(), nullable=False),
    )

    op.create_table(
        "measurement_alerts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("measurement_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "alert_type",
            sa.Enum(
                "severely_wasted",
                "wasted",
                "overweight",
                "obese",
                "severe_underweight",
                "underweight",
                name="alerttype",
            ),
            nullable=False,
        ),
        sa.Column(
            "severity",
            sa.Enum("critical", "high", "medium", name="alertseverity"),
            nullable=False,
        ),
        sa.Column("detail", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["measurement_id"],
            ["measurements.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_measurement_alerts_measurement_id",
        "measurement_alerts",
        ["measurement_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_measurement_alerts_measurement_id", table_name="measurement_alerts"
    )
    op.drop_table("measurement_alerts")
    sa.Enum(name="alertseverity").drop(op.get_bind())
    sa.Enum(name="alerttype").drop(op.get_bind())
    op.drop_constraint(
        "uq_measurements_idempotency_key", "measurements", type_="unique"
    )
    op.drop_column("measurements", "bmi")
    op.drop_column("measurements", "idempotency_key")
