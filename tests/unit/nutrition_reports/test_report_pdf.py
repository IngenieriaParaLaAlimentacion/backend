import uuid
from datetime import date, datetime, timezone

import pytest

from app.domain.nutrition_report import SummaryStatus
from app.reference_data.nutrition_references import NINO_7_9
from app.schemas.nutrition_reports.nutrition_report_schema import (
    NutritionReportResponse,
)
from app.services.nutrition_reports.analysis import build_analysis
from app.services.nutrition_reports.pdf import (
    _FETCHER,
    _logo_data_uri,
    build_context,
    render_report_html,
    render_report_pdf,
)
from tests.unit.nutrition.helpers import monthly_analysis

SUMMARY = {
    "overview": "El mes estuvo parejo.",
    "at_risk_nutrients": ["Calcio: sostiene los huesos."],
    "macros": "Los lípidos superan el rango.",
    "gapa_groups": "No hubo lácteos.",
    "incorporate": "Sumar leche.",
    "conclusion": "Conviene empezar por el calcio.",
    "limitations": [],
}


def make_report(summary=SUMMARY, analysis=None, **overrides) -> NutritionReportResponse:
    snapshot, milk_id = monthly_analysis()
    if analysis is None:
        analysis = build_analysis(snapshot, NINO_7_9, {milk_id: "Leche"}).model_dump(
            mode="json"
        )
    created = datetime(2026, 10, 15, 1, 30, tzinfo=timezone.utc)
    return NutritionReportResponse.model_validate(
        {
            "id": uuid.uuid4(),
            "establishment_id": uuid.uuid4(),
            "month": date(2026, 9, 1),
            "has_data": True,
            "reference_profile": "nino_7_9",
            "analysis": analysis,
            "summary_status": SummaryStatus.GENERATED,
            "summary": summary,
            "created_at": created,
            "updated_at": created,
            **overrides,
        }
    )


def test_the_month_is_written_out_and_the_generation_date_is_argentine():
    # 01:30 UTC is still the evening of the 14th in Buenos Aires.
    context = build_context(make_report(), "Comedor Test")

    assert context["month_label"] == "septiembre de 2026"
    assert context["generated_label"] == "14 de octubre de 2026"


def test_the_generation_date_is_the_last_time_the_report_was_calculated():
    # An empty month calculated again days later is printed with that later date.
    first = datetime(2026, 10, 1, 15, 0, tzinfo=timezone.utc)
    later = datetime(2026, 10, 14, 15, 0, tzinfo=timezone.utc)

    context = build_context(make_report(created_at=first, updated_at=later), "Test")

    assert context["generated_label"] == "14 de octubre de 2026"


def test_numbers_follow_the_argentine_format():
    context = build_context(make_report(), "Comedor Test")

    assert context["energy_kcal"] == "250.000"
    calcium = context["nutrients"][0]
    assert (calcium["amount"], calcium["adequacy"]) == ("310,0", "44")


def test_each_nutrient_row_carries_its_reference_and_minimum():
    calcium = build_context(make_report(), "Comedor Test")["nutrients"][0]

    assert (calcium["reference"], calcium["minimum"]) == ("395,5", "263,7")


def test_html_names_the_establishment_and_flags_the_nutrient_at_risk():
    html = render_report_html(make_report(), "Comedor Test")

    assert "Comedor Test" in html
    assert "En riesgo" in html


@pytest.mark.parametrize(
    ("conclusion", "shown"), [("Conviene empezar por el calcio.", True), ("", False)]
)
def test_the_conclusions_section_appears_only_when_the_ai_wrote_one(conclusion, shown):
    report = make_report(summary={**SUMMARY, "conclusion": conclusion})

    html = render_report_html(report, "Comedor Test")

    assert ("Conclusiones" in html) is shown


@pytest.mark.parametrize(
    ("limitations", "shown"),
    [(["Faltan datos de hierro en 3 alimentos."], True), ([], False)],
)
def test_the_limitations_section_appears_only_when_the_ai_wrote_some(
    limitations, shown
):
    report = make_report(summary={**SUMMARY, "limitations": limitations})

    html = render_report_html(report, "Comedor Test")

    assert ("Limitaciones de los datos" in html) is shown
    assert ("Faltan datos de hierro en 3 alimentos." in html) is shown


def test_a_month_without_data_has_no_scope_note():
    report = make_report(
        has_data=False,
        summary=None,
        summary_status=SummaryStatus.NOT_APPLICABLE,
        analysis={},
    )

    html = render_report_html(report, "Comedor Test")

    assert "Alcance de este informe" not in html
    assert "Alcance de este informe" in render_report_html(make_report(), "Comedor")


def test_text_written_by_people_or_the_ai_is_escaped():
    report = make_report(summary={**SUMMARY, "overview": "<b>Hola</b>"})

    html = render_report_html(report, "<script>alert(1)</script>")

    assert "<script>alert(1)</script>" not in html
    assert "<b>Hola</b>" not in html
    assert "&lt;script&gt;" in html


def test_the_pdf_is_a_pdf_file():
    pdf = render_report_pdf(make_report(), "Comedor Test")

    assert pdf.startswith(b"%PDF-")


@pytest.mark.parametrize("url", ["https://example.com/logo.png", "file:///etc/passwd"])
def test_the_pdf_does_not_load_external_resources(url):
    with pytest.raises(ValueError):
        _FETCHER.fetch(url)


def test_the_pdf_loads_the_logo_it_carries_inside():
    assert _FETCHER.fetch(_logo_data_uri())
