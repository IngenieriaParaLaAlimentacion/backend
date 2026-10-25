import uuid
from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest
from structlog.testing import capture_logs

from app.domain.nutrition import MonthlyIntakeAnalysis
from app.domain.nutrition_report import NutritionReportSortOrder, SummaryStatus
from app.domain.user import UserActor, UserRole
from app.exceptions.domain_exceptions import (
    EstablishmentAccessDeniedError,
    LlmClientError,
    NutritionReportConversionUnavailableError,
    NutritionReportMonthNotOverError,
    NutritionReportNotFoundError,
)
from app.models.nutrition.nutrition_report import NutritionReport
from app.reference_data.nutrition_references import NINO_7_9
from app.services.nutrition.nutrition_report_service import NutritionReportService
from app.services.nutrition.report_analysis import build_analysis
from tests.unit.nutrition.helpers import monthly_analysis

ESTABLISHMENT_ID = uuid.uuid4()
ADMIN = UserActor(user_id=uuid.uuid4(), role=UserRole.ADMIN)
SEPTEMBER = date(2026, 9, 1)

SUMMARY = {
    "overview": "El mes estuvo equilibrado.",
    "at_risk_nutrients": ["Calcio: 44% de lo esperado."],
    "macros": "Lípidos por encima del rango.",
    "gapa_groups": "Faltan los lácteos.",
    "incorporate": "Sumar leche.",
    "limitations": [],
}


@pytest.fixture(autouse=True)
def october_18(monkeypatch):
    monkeypatch.setattr(
        "app.services.nutrition.nutrition_report_service.today_in_argentina",
        lambda: date(2026, 10, 18),
    )


def named_food(food_id):
    food = MagicMock()
    food.id = food_id
    food.name = "Leche"
    return food


def make_service(analysis=None, saved=None, llm_result=SUMMARY):
    """A service over a mocked UoW holding ``saved``, a calculation returning
    ``analysis`` and an AI answering ``llm_result`` (an exception is raised)."""
    uow = AsyncMock()
    uow.nutrition_report_repo.get_by_month = AsyncMock(return_value=saved)
    uow.nutrition_report_repo.create = AsyncMock(side_effect=lambda report: report)
    uow.food_repo.get_by_ids = AsyncMock(
        side_effect=lambda ids: [named_food(food_id) for food_id in ids]
    )
    nutrition = MagicMock(profile=NINO_7_9)
    nutrition.analyze_monthly_intake = AsyncMock(return_value=analysis)
    llm = AsyncMock()
    llm.complete = AsyncMock(
        side_effect=llm_result if isinstance(llm_result, Exception) else None,
        return_value=None if isinstance(llm_result, Exception) else llm_result,
    )
    return NutritionReportService(uow, nutrition, llm), uow, nutrition, llm


def saved_report(summary_status, summary=None) -> NutritionReport:
    analysis, milk_id = monthly_analysis()
    return NutritionReport(
        id=uuid.uuid4(),
        establishment_id=ESTABLISHMENT_ID,
        month=SEPTEMBER,
        has_data=True,
        analysis=build_analysis(analysis, NINO_7_9, {milk_id: "Leche"}).model_dump(
            mode="json"
        ),
        reference_profile="nino_7_9",
        summary=summary,
        summary_status=summary_status,
    )


async def test_new_month_is_calculated_written_up_and_saved():
    analysis, _ = monthly_analysis()
    service, uow, _, llm = make_service(analysis)

    report, created = await service.get_or_generate_report(
        ESTABLISHMENT_ID, "2026-09", ADMIN
    )

    assert created is True
    assert (report.establishment_id, report.month) == (ESTABLISHMENT_ID, SEPTEMBER)
    assert report.has_data is True
    assert report.reference_profile == "nino_7_9"
    assert report.summary_status == SummaryStatus.GENERATED
    assert report.summary == SUMMARY
    assert report.analysis["energy_kcal"] == analysis.indicators.energy_kcal
    llm.complete.assert_awaited_once()
    uow.nutrition_report_repo.create.assert_awaited_once_with(report)
    uow.commit.assert_awaited_once()


async def test_report_is_looked_up_only_after_taking_the_lock():
    analysis, _ = monthly_analysis()
    service, uow, _, _ = make_service(analysis)

    await service.get_or_generate_report(ESTABLISHMENT_ID, "2026-09", ADMIN)

    calls = [call[0] for call in uow.nutrition_report_repo.mock_calls]
    assert calls.index("lock") < calls.index("get_by_month")


async def test_saved_report_is_returned_without_calculating_or_calling_the_ai():
    saved = saved_report(SummaryStatus.GENERATED, SUMMARY)
    service, uow, nutrition, llm = make_service(saved=saved)

    report, created = await service.get_or_generate_report(
        ESTABLISHMENT_ID, "2026-09", ADMIN
    )

    assert (report, created) == (saved, False)
    nutrition.analyze_monthly_intake.assert_not_awaited()
    llm.complete.assert_not_awaited()
    uow.commit.assert_not_awaited()


async def test_month_without_data_is_saved_without_calling_the_ai():
    service, uow, _, llm = make_service(MonthlyIntakeAnalysis(has_data=False))

    report, created = await service.get_or_generate_report(
        ESTABLISHMENT_ID, "2026-09", ADMIN
    )

    assert created is True
    assert report.has_data is False
    assert report.summary_status == SummaryStatus.NOT_APPLICABLE
    assert report.summary is None
    llm.complete.assert_not_awaited()
    uow.commit.assert_awaited_once()


async def test_month_whose_foods_cannot_be_converted_is_not_saved():
    analysis = MonthlyIntakeAnalysis(
        has_data=False, foods_without_conversion=[uuid.uuid4(), uuid.uuid4()]
    )
    service, uow, _, _ = make_service(analysis)

    with pytest.raises(NutritionReportConversionUnavailableError):
        await service.get_or_generate_report(ESTABLISHMENT_ID, "2026-09", ADMIN)

    uow.nutrition_report_repo.create.assert_not_awaited()
    uow.commit.assert_not_awaited()


async def test_foods_left_out_of_the_calculation_are_saved_with_their_names():
    analysis, _ = monthly_analysis()
    left_out = uuid.uuid4()
    analysis.foods_without_conversion = [left_out]
    service, _, _, _ = make_service(analysis)

    report, _ = await service.get_or_generate_report(ESTABLISHMENT_ID, "2026-09", ADMIN)

    assert report.analysis["foods_without_conversion"] == [
        {"food_id": str(left_out), "name": "Leche"}
    ]


@pytest.mark.parametrize(
    "llm_result",
    [LlmClientError("provider down"), {**SUMMARY, "overview": "  "}],
    ids=["ai-fails", "ai-answers-badly"],
)
async def test_analysis_is_saved_even_when_the_summary_cannot_be_had(llm_result):
    analysis, _ = monthly_analysis()
    service, uow, _, _ = make_service(analysis, llm_result=llm_result)

    report, created = await service.get_or_generate_report(
        ESTABLISHMENT_ID, "2026-09", ADMIN
    )

    assert created is True
    assert report.has_data is True
    assert report.summary_status == SummaryStatus.UNAVAILABLE
    assert report.summary is None
    assert report.analysis["energy_kcal"] == analysis.indicators.energy_kcal
    uow.commit.assert_awaited_once()


@pytest.mark.parametrize(
    ("llm_result", "reason"),
    [
        (LlmClientError("secret provider detail"), "provider_error"),
        ({**SUMMARY, "overview": "  "}, "invalid_output"),
    ],
    ids=["ai-fails", "ai-answers-badly"],
)
async def test_failed_summary_is_logged_by_reason_without_the_providers_message(
    llm_result, reason
):
    analysis, _ = monthly_analysis()
    service, _, _, _ = make_service(analysis, llm_result=llm_result)

    with capture_logs() as logs:
        await service.get_or_generate_report(ESTABLISHMENT_ID, "2026-09", ADMIN)

    [entry] = [log for log in logs if log["event"] == "nutrition_report.summary_failed"]
    assert (entry["stage"], entry["reason"]) == ("summary", reason)
    assert entry["prompt_version"] == "v1"
    assert "secret provider detail" not in str(logs)


async def test_unavailable_summary_is_written_again_without_recalculating():
    saved = saved_report(SummaryStatus.UNAVAILABLE)
    service, uow, nutrition, _ = make_service(saved=saved)

    report, created = await service.get_or_generate_report(
        ESTABLISHMENT_ID, "2026-09", ADMIN
    )

    assert (report, created) == (saved, False)
    assert report.summary_status == SummaryStatus.GENERATED
    assert report.summary == SUMMARY
    nutrition.analyze_monthly_intake.assert_not_awaited()
    uow.commit.assert_awaited_once()


async def test_unavailable_summary_stays_so_when_the_ai_fails_again():
    saved = saved_report(SummaryStatus.UNAVAILABLE)
    service, uow, _, _ = make_service(saved=saved, llm_result=LlmClientError("down"))

    report, created = await service.get_or_generate_report(
        ESTABLISHMENT_ID, "2026-09", ADMIN
    )

    assert (report, created) == (saved, False)
    assert report.summary_status == SummaryStatus.UNAVAILABLE
    uow.commit.assert_not_awaited()


@pytest.mark.parametrize("month", ["2026-10", "2026-11"], ids=["current", "future"])
async def test_month_that_is_not_over_is_rejected_before_any_work(month):
    analysis, _ = monthly_analysis()
    service, uow, nutrition, _ = make_service(analysis)

    with pytest.raises(NutritionReportMonthNotOverError):
        await service.get_or_generate_report(ESTABLISHMENT_ID, month, ADMIN)

    uow.nutrition_report_repo.lock.assert_not_awaited()
    nutrition.analyze_monthly_intake.assert_not_awaited()


async def test_saved_report_is_read_without_generating_anything():
    saved = saved_report(SummaryStatus.UNAVAILABLE)
    service, uow, nutrition, llm = make_service(saved=saved)

    report = await service.get_report(ESTABLISHMENT_ID, "2026-09", ADMIN)

    # Reading never writes the unavailable summary again, as generating would.
    assert report is saved
    nutrition.analyze_monthly_intake.assert_not_awaited()
    llm.complete.assert_not_awaited()
    uow.nutrition_report_repo.lock.assert_not_awaited()
    uow.commit.assert_not_awaited()


async def test_saved_report_can_be_read_by_a_service_without_calculator_or_ai():
    saved = saved_report(SummaryStatus.GENERATED, SUMMARY)
    uow = AsyncMock()
    uow.nutrition_report_repo.get_by_month = AsyncMock(return_value=saved)

    report = await NutritionReportService(uow).get_report(
        ESTABLISHMENT_ID, "2026-09", ADMIN
    )

    assert report is saved


async def test_month_without_a_saved_report_is_not_found_and_not_generated():
    service, uow, nutrition, llm = make_service()

    with pytest.raises(NutritionReportNotFoundError):
        await service.get_report(ESTABLISHMENT_ID, "2026-09", ADMIN)

    nutrition.analyze_monthly_intake.assert_not_awaited()
    llm.complete.assert_not_awaited()
    uow.nutrition_report_repo.create.assert_not_awaited()


@pytest.mark.parametrize(
    ("method", "args", "kwargs"),
    [
        ("get_or_generate_report", ("2026-09",), {}),
        ("get_report", ("2026-09",), {}),
        (
            "list_reports",
            (),
            {
                "sort_order": NutritionReportSortOrder.MONTH_DESC,
                "page": 1,
                "page_size": 20,
            },
        ),
    ],
)
async def test_field_worker_without_approved_access_cannot_get_a_report(
    method, args, kwargs
):
    service, uow, _, _ = make_service()
    uow.user_establishment_repo.get_relation = AsyncMock(return_value=None)
    worker = UserActor(user_id=uuid.uuid4(), role=UserRole.FIELD_WORKER)

    with pytest.raises(EstablishmentAccessDeniedError):
        await getattr(service, method)(ESTABLISHMENT_ID, *args, worker, **kwargs)

    repo = uow.nutrition_report_repo
    repo.lock.assert_not_awaited()
    repo.get_by_month.assert_not_awaited()
    repo.list_by_establishment.assert_not_awaited()
