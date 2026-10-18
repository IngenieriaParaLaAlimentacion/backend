import uuid
from datetime import date, datetime, timezone

from app.domain.nutrition_report import SummaryStatus
from app.schemas.nutrition.nutrition_report_schema import NutritionReportResponse


def test_response_shows_the_stored_month_as_year_and_month():
    """A report stored under the first day of a month is shown as YYYY-MM."""
    now = datetime(2026, 10, 1, tzinfo=timezone.utc)
    stored = {
        "id": uuid.uuid4(),
        "establishment_id": uuid.uuid4(),
        "month": date(2026, 9, 1),
        "has_data": False,
        "reference_profile": "nino_7_9",
        "analysis": {},
        "summary_status": SummaryStatus.NOT_APPLICABLE,
        "created_at": now,
        "updated_at": now,
    }

    assert NutritionReportResponse.model_validate(stored).month == "2026-09"
