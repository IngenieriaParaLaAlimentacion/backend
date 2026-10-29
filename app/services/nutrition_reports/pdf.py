import base64
from functools import cache
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from weasyprint import HTML, URLFetcher

from app.domain.nutrition import LimitedNutrient
from app.domain.nutrition_report import (
    GAPA_GROUP_LABELS,
    LIMIT_LABELS,
    MACRO_LABELS,
    NUTRIENT_LABELS,
    NUTRIENT_NOTES,
)
from app.schemas.nutrition_reports.nutrition_report_schema import (
    NutritionReportResponse,
)
from app.utils.dates import ARGENTINA_TZ

_APP = Path(__file__).resolve().parents[2]
_LOGO = _APP / "static" / "emails" / "raiz-logo.png"

# The palette and fonts live in the shared theme, which the backoffice's styles
# mirror, so the report takes them from it instead of repeating them.
_ENV = Environment(
    loader=FileSystemLoader(
        [_APP / "templates" / "reports", _APP / "templates" / "shared"]
    ),
    autoescape=select_autoescape(["html"]),
    undefined=StrictUndefined,
)

# The only resource a report loads is its logo, which travels inside as a data URI.
_FETCHER = URLFetcher(allowed_protocols={"data"}, allow_redirects=False)

_MONTHS = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)


def _number(value: float, decimals: int = 1) -> str:
    """Format a number the Argentine way: a dot for thousands, a comma for decimals."""
    text = f"{value:,.{decimals}f}"
    return text.replace(",", "_").replace(".", ",").replace("_", ".")


def _date(value) -> str:
    """Write a date as, for example, ``14 de octubre de 2026``."""
    return f"{value.day} de {_MONTHS[value.month - 1]} de {value.year}"


@cache
def _logo_data_uri() -> str:
    """Return the logo as a data URI, so the PDF never has to fetch it."""
    return "data:image/png;base64," + base64.b64encode(_LOGO.read_bytes()).decode()


def build_context(
    report: NutritionReportResponse, establishment_name: str
) -> dict[str, Any]:
    """Return what the report template shows, written for a reader.

    Raises:
        ValueError: the report has data but no AI summary to print.
    """
    year, month = map(int, report.month.split("-"))
    context: dict[str, Any] = {
        "establishment_name": establishment_name,
        "month_label": f"{_MONTHS[month - 1]} de {year}",
        "generated_label": _date(report.updated_at.astimezone(ARGENTINA_TZ)),
        "logo_data_uri": _logo_data_uri(),
        "has_data": report.has_data,
        "scope_note": report.scope_note,
    }
    if not report.has_data:
        return context
    if report.summary is None:
        raise ValueError("A report with data needs its summary to be printed")

    analysis = report.analysis
    nutrients = []
    for item in analysis.nutrients:
        label = NUTRIENT_LABELS[item.nutrient]
        nutrients.append(
            {
                "name": label.name,
                "unit": label.unit,
                "amount": _number(item.amount_per_1000_kcal),
                "reference": _number(item.reference_per_1000_kcal),
                "minimum": _number(item.minimum_per_1000_kcal),
                "adequacy": _number(item.adequacy_percent, 0),
                "at_risk": item.at_risk,
            }
        )
    context.update(
        energy_kcal=_number(analysis.energy_kcal, 0),
        mean_adequacy=_number(analysis.mean_adequacy_percent),
        nutrient_count=len(nutrients),
        at_risk_count=sum(row["at_risk"] for row in nutrients),
        nutrients=nutrients,
        nutrient_notes=[
            NUTRIENT_NOTES[item.nutrient]
            for item in analysis.nutrients
            if item.nutrient in NUTRIENT_NOTES
        ],
        macros=[
            {
                "name": MACRO_LABELS[item.macro],
                "share": _number(item.energy_share_percent, 0),
                "min": _number(item.min_percent, 0),
                "max": _number(item.max_percent, 0),
                "in_range": item.in_range,
            }
            for item in analysis.macros
        ],
        groups=[
            {
                "name": GAPA_GROUP_LABELS[item.group],
                "share": _number(item.energy_share_percent, 0),
                "missing": item.missing,
            }
            for item in analysis.gapa_groups
        ],
        sources=[
            {
                "nutrient": NUTRIENT_LABELS[item.nutrient].name,
                "unit": NUTRIENT_LABELS[item.nutrient].unit,
                "foods": [
                    {"name": food.name, "amount": _number(food.amount_per_100_kcal)}
                    for food in item.foods
                ],
            }
            for item in analysis.top_sources
        ],
        limits=[
            {
                "name": LIMIT_LABELS[LimitedNutrient(item.code)].name,
                "unit": LIMIT_LABELS[LimitedNutrient(item.code)].unit,
                "amount": _number(item.amount_per_1000_kcal),
            }
            for item in analysis.limits
        ],
        left_out=[food.name for food in analysis.foods_without_conversion],
        summary=report.summary,
    )
    return context


def render_report_html(report: NutritionReportResponse, establishment_name: str) -> str:
    """Return the HTML of a saved report, ready to be turned into a PDF."""
    template = _ENV.get_template("nutrition_report.html")
    return template.render(**build_context(report, establishment_name))


def render_report_pdf(
    report: NutritionReportResponse, establishment_name: str
) -> bytes:
    """Return a saved report as a PDF file. It is CPU-bound work."""
    html = render_report_html(report, establishment_name)
    return HTML(string=html, url_fetcher=_FETCHER).write_pdf()
