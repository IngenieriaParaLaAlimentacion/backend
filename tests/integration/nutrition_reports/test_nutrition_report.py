import asyncio
import uuid

import pytest
from limits.aio.strategies import MovingWindowRateLimiter
from limits.storage import storage_from_string

from app.config.settings import settings
from app.core import rate_limit
from app.domain.nutrition import PrioritizedNutrient
from app.domain.user import UserRole
from app.schemas.nutrition_reports.nutrition_report_schema import (
    NutritionReportAnalysis,
    ReportFoodWithoutConversion,
    ReportNutrient,
)
from app.utils.dates import today_in_argentina
from tests.integration.nutrition_reports.helpers import (
    AUGUST,
    GENERATED,
    MARCH,
    MARCH_INTAKE,
    NOT_APPLICABLE,
    OCTOBER,
    SEPTEMBER,
    SUMMARY,
    UNAVAILABLE,
    add_intake,
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
            reference_per_1000_kcal=705.0,
            minimum_per_1000_kcal=470.0,
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


def pdf_url(establishment_id, month="2026-09") -> str:
    return report_url(establishment_id, month) + "/pdf"


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


@pytest.mark.parametrize("url_for", [report_url, pdf_url], ids=["detail", "pdf"])
async def test_month_without_a_saved_report_returns_404(
    url_for, client, admin_headers, db_establishment
):
    response = await client.get(url_for(db_establishment.id), headers=admin_headers)

    assert response.status_code == 404


async def test_report_of_another_establishment_is_not_returned(
    client, admin_headers, db_establishment
):
    other = await save_other_establishment()
    await save(make_report(other.id))

    response = await client.get(report_url(db_establishment.id), headers=admin_headers)

    assert response.status_code == 404


ROUTES = pytest.mark.parametrize(
    ("method", "url_for"),
    [("GET", report_url), ("GET", list_url), ("PUT", report_url), ("GET", pdf_url)],
    ids=["detail", "list", "put", "pdf"],
)


@ROUTES
async def test_unknown_establishment_returns_404(
    method, url_for, client, admin_headers, report_llm
):
    response = await client.request(
        method, url_for(uuid.uuid4()), headers=admin_headers
    )

    assert response.status_code == 404


@ROUTES
async def test_field_worker_returns_403_even_with_approved_access_to_the_establishment(
    method, url_for, client, field_worker_with_access, db_establishment, report_llm
):
    # Only the role can keep them out: the establishment access check lets them in.
    headers, _ = field_worker_with_access
    await save(make_report(db_establishment.id))

    response = await client.request(
        method, url_for(db_establishment.id), headers=headers
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


async def test_report_is_generated_once_and_then_returned_as_saved(
    client, admin_headers, db_establishment, rice_in_march, report_llm
):
    url = report_url(db_establishment.id, MARCH)

    first = await client.put(url, headers=admin_headers)
    second = await client.put(url, headers=admin_headers)

    assert (first.status_code, second.status_code) == (201, 200)
    body = first.json()
    assert (body["month"], body["has_data"]) == (MARCH, True)
    assert (body["summary_status"], body["summary"]) == ("generated", SUMMARY)
    assert second.json()["id"] == body["id"]
    assert len(report_llm.calls) == 1


async def test_month_saved_without_data_is_filled_in_once_intakes_are_loaded(
    client,
    admin_headers,
    db_establishment,
    energy_values,
    foods,
    make_user_with_role,
    report_llm,
):
    url = report_url(db_establishment.id, MARCH)
    first = await client.put(url, headers=admin_headers)
    _, responsible_id = await make_user_with_role(UserRole.FIELD_WORKER)
    await add_intake(
        db_establishment.id, responsible_id, MARCH_INTAKE, [(foods.rice, "2")]
    )

    second = await client.put(url, headers=admin_headers)

    assert (first.status_code, first.json()["has_data"]) == (201, False)
    assert (second.status_code, second.json()["has_data"]) == (200, True)
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["summary_status"] == "generated"
    assert len(report_llm.calls) == 1


async def test_year_zero_is_rejected_as_an_invalid_month(
    client, admin_headers, db_establishment
):
    response = await client.get(
        report_url(db_establishment.id, "0000-01"), headers=admin_headers
    )

    assert response.status_code == 422


async def test_generation_over_its_time_budget_returns_504_and_saves_nothing(
    client, admin_headers, db_establishment, rice_in_march, report_llm, monkeypatch
):
    monkeypatch.setattr(settings, "report_generation_timeout_seconds", 0.1)
    report_llm.delay = 5
    url = report_url(db_establishment.id, MARCH)

    response = await asyncio.wait_for(client.put(url, headers=admin_headers), 2)
    saved = await client.get(url, headers=admin_headers)

    assert response.status_code == 504
    assert response.json()["type"] == "/errors/nutrition/report-generation-timeout"
    assert saved.status_code == 404


async def test_month_without_intakes_is_saved_as_no_data_without_calling_the_ai(
    client, admin_headers, db_establishment, report_llm
):
    response = await client.put(
        report_url(db_establishment.id, "2026-02"), headers=admin_headers
    )

    assert response.status_code == 201
    body = response.json()
    assert (body["has_data"], body["summary_status"], body["summary"]) == (
        False,
        "not_applicable",
        None,
    )
    assert report_llm.calls == []


async def test_report_with_a_failed_summary_is_written_again_on_the_next_request(
    client, admin_headers, db_establishment, rice_in_march, report_llm
):
    url = report_url(db_establishment.id, MARCH)
    report_llm.error = True
    first = await client.put(url, headers=admin_headers)
    report_llm.error = False

    second = await client.put(url, headers=admin_headers)

    assert (first.status_code, first.json()["summary_status"]) == (201, "unavailable")
    assert (second.status_code, second.json()["summary_status"]) == (200, "generated")
    assert second.json()["id"] == first.json()["id"]


async def test_month_whose_foods_cannot_be_converted_returns_409_and_saves_nothing(
    client,
    admin_headers,
    db_establishment,
    energy_values,
    foods,
    make_user_with_role,
    report_llm,
):
    _, responsible_id = await make_user_with_role(UserRole.FIELD_WORKER)
    # Eggs are counted in units and have no reviewed weight per unit.
    await add_intake(
        db_establishment.id, responsible_id, MARCH_INTAKE, [(foods.eggs, "10")]
    )
    url = report_url(db_establishment.id, MARCH)

    response = await client.put(url, headers=admin_headers)
    saved = await client.get(url, headers=admin_headers)

    assert response.status_code == 409
    assert saved.status_code == 404
    assert report_llm.calls == []


async def test_current_month_returns_422(
    client, admin_headers, db_establishment, report_llm
):
    month = today_in_argentina().strftime("%Y-%m")

    response = await client.put(
        report_url(db_establishment.id, month), headers=admin_headers
    )

    assert response.status_code == 422
    assert report_llm.calls == []


async def test_simultaneous_requests_for_a_month_call_the_ai_once(
    client, admin_headers, db_establishment, rice_in_march, report_llm
):
    report_llm.delay = 0.3
    url = report_url(db_establishment.id, MARCH)

    responses = await asyncio.gather(
        client.put(url, headers=admin_headers), client.put(url, headers=admin_headers)
    )

    assert sorted(response.status_code for response in responses) == [200, 201]
    assert responses[0].json()["id"] == responses[1].json()["id"]
    assert len(report_llm.calls) == 1


async def test_every_request_counts_toward_the_ai_quota_even_for_a_saved_report(
    client, admin_headers, db_establishment, rice_in_march, report_llm, monkeypatch
):
    memory = MovingWindowRateLimiter(storage_from_string("async+memory://"))
    monkeypatch.setattr(
        rate_limit, "_limiter", rate_limit.ResilientLimiter(memory, memory)
    )
    monkeypatch.setattr(settings, "rate_limit_ai_user", "1/hour")
    url = report_url(db_establishment.id, MARCH)

    first = await client.put(url, headers=admin_headers)
    second = await client.put(url, headers=admin_headers)

    assert (first.status_code, second.status_code) == (201, 429)
    assert "retry-after" in second.headers
    assert len(report_llm.calls) == 1


async def test_saved_report_downloads_as_a_pdf_file(
    client, admin_headers, db_establishment
):
    await save(make_report(db_establishment.id, analysis=ANALYSIS))

    response = await client.get(pdf_url(db_establishment.id), headers=admin_headers)

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"] == (
        'attachment; filename="nutrition-report-2026-09.pdf"'
    )
    assert response.content.startswith(b"%PDF-")


async def test_month_without_intakes_downloads_as_a_pdf_file(
    client, admin_headers, db_establishment
):
    await save(make_report(db_establishment.id, state=NOT_APPLICABLE))

    response = await client.get(pdf_url(db_establishment.id), headers=admin_headers)

    assert response.status_code == 200
    assert response.content.startswith(b"%PDF-")


async def test_pdf_of_a_report_whose_summary_is_unavailable_returns_409(
    client, admin_headers, db_establishment
):
    await save(make_report(db_establishment.id, analysis=ANALYSIS, state=UNAVAILABLE))

    response = await client.get(pdf_url(db_establishment.id), headers=admin_headers)

    assert response.status_code == 409
    assert response.json()["type"].endswith("/nutrition/report-summary-unavailable")
