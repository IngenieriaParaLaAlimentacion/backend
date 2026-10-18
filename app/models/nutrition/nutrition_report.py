import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.domain.nutrition_report import SummaryStatus

from ..base import Base


class NutritionReport(Base):
    """The nutrition report of an establishment for one calendar month.

    Holds the analysis as it was calculated and the summary as the AI wrote it.
    """

    __tablename__ = "nutrition_reports"
    __table_args__ = (
        UniqueConstraint(
            "establishment_id",
            "month",
            name="uq_nutrition_reports_establishment_id_month",
        ),
        CheckConstraint(
            "EXTRACT(day FROM month) = 1",
            name="ck_nutrition_reports_month_is_first_day",
        ),
        # The summary text exists exactly when the AI wrote it.
        CheckConstraint(
            "(summary_status = 'generated') = (summary_text IS NOT NULL)",
            name="ck_nutrition_reports_summary_text_matches_status",
        ),
        # A month without intakes has nothing to summarize, and one with intakes
        # always has a summary to write, even if it could not be written yet.
        CheckConstraint(
            "has_data = (summary_status <> 'not_applicable')",
            name="ck_nutrition_reports_has_data_matches_summary_status",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    establishment_id = Column(
        UUID(as_uuid=True),
        ForeignKey("establishments.id", ondelete="RESTRICT"),
        nullable=False,
    )
    # The first day of the month the report covers.
    month = Column(Date, nullable=False)
    has_data = Column(Boolean, nullable=False)
    analysis = Column(JSONB, nullable=False)
    reference_profile = Column(String, nullable=False)
    summary_text = Column(Text, nullable=True)
    summary_status = Column(
        SAEnum(
            SummaryStatus,
            values_callable=lambda x: [e.value for e in x],
            name="nutritionreportsummarystatus",
        ),
        nullable=False,
    )
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
