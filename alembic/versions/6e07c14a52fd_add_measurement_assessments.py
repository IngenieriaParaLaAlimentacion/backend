"""Add versioned measurement assessments and stature method."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "6e07c14a52fd"
down_revision = "8d3f6a1c9e27"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("measurements", sa.Column("stature_method", sa.String(16)))
    op.create_check_constraint(
        "ck_measurements_stature_method",
        "measurements",
        "stature_method IN ('recumbent', 'standing')",
    )
    op.create_table(
        "measurement_assessments",
        sa.Column(
            "measurement_id",
            UUID(as_uuid=True),
            sa.ForeignKey("measurements.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ruleset_version", sa.String(128), nullable=False),
        sa.Column("indicator", sa.String(16), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("classification", sa.String(64), nullable=True),
        sa.Column("z_score", sa.Float(), nullable=True),
        sa.Column("reference_version", sa.String(128), nullable=True),
        sa.Column("alert_severity", sa.String(12), nullable=True),
        sa.Column("alert_detail", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint(
            "measurement_id",
            "ruleset_version",
            "indicator",
            name="pk_measurement_assessments",
        ),
        sa.CheckConstraint(
            "indicator IN ('length_for_age', 'weight_for_age', 'bmi_for_age', "
            "'height_for_age', 'adult_bmi')",
            name="ck_measurement_assessments_indicator",
        ),
        sa.CheckConstraint(
            "status IN ('evaluated', 'insufficient_data', 'not_applicable')",
            name="ck_measurement_assessments_status",
        ),
        sa.CheckConstraint(
            "(status = 'evaluated' AND classification IS NOT NULL AND "
            "reference_version IS NOT NULL AND "
            "((indicator = 'adult_bmi' AND z_score IS NULL) OR "
            "(indicator <> 'adult_bmi' AND z_score IS NOT NULL))) OR "
            "(status <> 'evaluated' AND classification IS NULL AND "
            "z_score IS NULL AND alert_severity IS NULL)",
            name="ck_measurement_assessments_result",
        ),
        sa.CheckConstraint(
            "(alert_severity IS NULL AND alert_detail IS NULL) OR "
            "(alert_severity IS NOT NULL AND "
            "alert_severity IN ('medium', 'high', 'critical') AND "
            "alert_detail IS NOT NULL)",
            name="ck_measurement_assessments_alert",
        ),
    )
    op.create_index(
        "ix_measurement_assessments_filter",
        "measurement_assessments",
        ["ruleset_version", "indicator", "classification", "measurement_id"],
        postgresql_where=sa.text("status = 'evaluated'"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_measurement_assessments_filter",
        table_name="measurement_assessments",
    )
    op.drop_table("measurement_assessments")
    op.drop_constraint("ck_measurements_stature_method", "measurements", type_="check")
    op.drop_column("measurements", "stature_method")
