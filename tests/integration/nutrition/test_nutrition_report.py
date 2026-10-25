import uuid

import pytest

from app.domain.nutrition import PrioritizedNutrient
from app.schemas.nutrition.nutrition_report_schema import (
    NutritionReportAnalysis,
    ReportFoodWithoutConversion,
    ReportNutrient,
)
from tests.integration.nutrition.helpers import (
    AUGUST,
    GENERATED,
    NOT_APPLICABLE,
    OCTOBER,
    SEPTEMBER,
    UNAVAILABLE,
    make_report,
    save,
    save_other_establishment,
)

ROOT = "/api/v1"

ANALYSIS = NutritionReportAnalysis(
    energy_kcal=250000.0,
    mean_adequacy_percent=72.0,
    nutrients=[
        ReportNutrient(
            nutrient=PrioritizedNutrient.CALCIUM,
            amount_per_1000_kcal=310.0,
            adequacy_percent=44.0,
            adequacy_capped_percent=44.0,
            at_risk=True,
        )
    ],
    foods_without_conversion=[
        ReportFoodWithoutConversion(food_id=uuid.uuid4(), name="Arroz")
    ],
).model_dump(mode="json")


def report_url(establishment_id, month="2026-09") -> str:
    return f"{ROOT}/establishments/{establishment_id}/nutrition-reports/{month}"


def list_url(establishment_id) -> str:
    return f"{ROOT}/establishments/{establishment_id}/nutrition-reports"


@pytest.mark.parametrize("headers", ["admin_headers", "analyst_headers"])
async def test_admin_and_analyst_get_the_saved_report(
    headers, request, client, db_establishment
):
    await save(make_report(db_establishment.id, analysis=ANALYSIS))

    response = await client.get(
        report_url(db_establishment.id), headers=request.getfixturevalue(headers)
    )

    assert response.status_code == 200
    body = response.json()
    assert body["establishment_id"] == str(db_establishment.id)
    assert body["month"] == "2026-09"
    assert body["analysis"] == ANALYSIS
    assert body["scope_note"]


@pytest.mark.parametrize(
    "state", [GENERATED, UNAVAILABLE, NOT_APPLICABLE], ids=lambda state: state[1].value
)
async def test_report_shows_the_state_of_its_summary(
    state, client, admin_headers, db_establishment
):
    has_data, summary_status, summary = state
    await save(make_report(db_establishment.id, state=state))

    response = await client.get(report_url(db_establishment.id), headers=admin_headers)

    body = response.json()
    assert (body["has_data"], body["summary_status"], body["summary"]) == (
        has_data,
        summary_status.value,
        summary,
    )


async def test_month_without_a_saved_report_returns_404(
    client, admin_headers, db_establishment
):
    response = await client.get(report_url(db_establishment.id), headers=admin_headers)

    assert response.status_code == 404


async def test_report_of_another_establishment_is_not_returned(
    client, admin_headers, db_establishment
):
    other = await save_other_establishment()
    await save(make_report(other.id))

    response = await client.get(report_url(db_establishment.id), headers=admin_headers)

    assert response.status_code == 404


@pytest.mark.parametrize("url_for", [report_url, list_url], ids=["detail", "list"])
async def test_unknown_establishment_returns_404(url_for, client, admin_headers):
    response = await client.get(url_for(uuid.uuid4()), headers=admin_headers)

    assert response.status_code == 404


@pytest.mark.parametrize("url_for", [report_url, list_url], ids=["detail", "list"])
async def test_field_worker_returns_403(
    url_for, client, field_worker_headers, db_establishment
):
    await save(make_report(db_establishment.id))

    response = await client.get(
        url_for(db_establishment.id), headers=field_worker_headers
    )

    assert response.status_code == 403


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("", ["2026-10", "2026-09", "2026-08"]),
        ("?sort_order=month_asc", ["2026-08", "2026-09", "2026-10"]),
    ],
    ids=["newest-first-by-default", "oldest-first-on-request"],
)
async def test_reports_are_listed_by_month(
    query, expected, client, admin_headers, db_establishment
):
    for month in (SEPTEMBER, AUGUST, OCTOBER):
        await save(make_report(db_establishment.id, month=month))

    response = await client.get(
        list_url(db_establishment.id) + query, headers=admin_headers
    )

    assert response.status_code == 200
    assert [item["month"] for item in response.json()["items"]] == expected


async def test_reports_are_listed_a_page_at_a_time(
    client, admin_headers, db_establishment
):
    for month in (AUGUST, SEPTEMBER, OCTOBER):
        await save(make_report(db_establishment.id, month=month))

    response = await client.get(
        list_url(db_establishment.id) + "?page=2&page_size=1", headers=admin_headers
    )

    body = response.json()
    assert [item["month"] for item in body["items"]] == ["2026-09"]
    assert (body["total"], body["page"], body["page_size"], body["total_pages"]) == (
        3,
        2,
        1,
        3,
    )


async def test_listed_report_shows_only_its_basics(
    client, admin_headers, db_establishment
):
    await save(make_report(db_establishment.id, analysis=ANALYSIS))

    response = await client.get(list_url(db_establishment.id), headers=admin_headers)

    [item] = response.json()["items"]
    assert set(item) == {"id", "month", "has_data", "summary_status", "created_at"}


async def test_establishment_without_reports_lists_none(
    client, admin_headers, db_establishment
):
    response = await client.get(list_url(db_establishment.id), headers=admin_headers)

    assert response.status_code == 200
    body = response.json()
    assert (body["items"], body["total"]) == ([], 0)
