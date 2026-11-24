import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from ..base import Base


class MeasurementAssessment(Base):
    """Stored indicator outcome for a measurement and ruleset version."""

    __tablename__ = "measurement_assessments"
    __table_args__ = (
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
        sa.Index(
            "ix_measurement_assessments_filter",
            "ruleset_version",
            "indicator",
            "classification",
            "measurement_id",
            postgresql_where=sa.text("status = 'evaluated'"),
        ),
    )

    measurement_id = sa.Column(
        UUID(as_uuid=True),
        sa.ForeignKey("measurements.id", ondelete="CASCADE"),
        primary_key=True,
    )
    ruleset_version = sa.Column(sa.String(128), primary_key=True)
    indicator = sa.Column(sa.String(16), primary_key=True)
    status = sa.Column(sa.String(24), nullable=False)
    classification = sa.Column(sa.String(64))
    z_score = sa.Column(sa.Float)
    reference_version = sa.Column(sa.String(128))
    alert_severity = sa.Column(sa.String(12))
    alert_detail = sa.Column(sa.Text)

    measurement = relationship("Measurement", back_populates="assessments")
