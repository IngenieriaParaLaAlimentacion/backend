import uuid
from datetime import date, datetime, timezone

from app.domain.nutrition_report import SummaryStatus
from app.schemas.nutrition.nutrition_report_schema import (
    NutritionReportAnalysis,
    NutritionReportListItem,
    NutritionReportResponse,
)


def stored_report() -> dict:
    """A report as stored, which holds no scope note."""
    now = datetime(2026, 10, 1, tzinfo=timezone.utc)
    return {
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


def test_response_shows_the_stored_month_as_year_and_month():
    """A report stored under the first day of a month is shown as YYYY-MM."""
    response = NutritionReportResponse.model_validate(stored_report())

    assert response.month == "2026-09"


def test_response_always_carries_the_scope_note():
    """Every report carries the fixed note, although it is not stored with it."""
    response = NutritionReportResponse.model_validate(stored_report())

    assert response.scope_note.strip()


def test_list_item_shows_the_basics_of_a_report_without_its_analysis_or_summary():
    """A listed report has its month as YYYY-MM and nothing of the full report."""
    item = NutritionReportListItem.model_validate(stored_report())

    assert item.month == "2026-09"
    assert set(item.model_dump()) == {
        "id",
        "month",
        "has_data",
        "summary_status",
        "created_at",
    }


def test_analysis_saved_before_the_reference_was_stored_still_loads():
    old = {
        "nutrients": [
            {
                "nutrient": "calcio",
                "amount_per_1000_kcal": 200.0,
                "adequacy_percent": 51.0,
                "adequacy_capped_percent": 51.0,
                "at_risk": True,
            }
        ]
    }

    [calcium] = NutritionReportAnalysis.model_validate(old).nutrients

    assert (calcium.reference_per_1000_kcal, calcium.minimum_per_1000_kcal) == (
        None,
        None,
    )
