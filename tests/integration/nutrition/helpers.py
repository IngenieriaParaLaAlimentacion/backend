from datetime import date

from app.domain.nutrition_report import SummaryStatus
from app.models.nutrition.nutrition_report import NutritionReport

SEPTEMBER = date(2026, 9, 1)
OCTOBER = date(2026, 10, 1)

SUMMARY = {
    "overview": "El mes estuvo equilibrado.",
    "at_risk_nutrients": ["Calcio: 44% de lo esperado."],
    "macros": "Dentro de los rangos.",
    "gapa_groups": "Falta el grupo de lácteos.",
    "incorporate": "Sumar leche.",
    "limitations": [],
}

GENERATED = (True, SummaryStatus.GENERATED, SUMMARY)
UNAVAILABLE = (True, SummaryStatus.UNAVAILABLE, None)
NOT_APPLICABLE = (False, SummaryStatus.NOT_APPLICABLE, None)


def make_report(
    establishment_id, *, month=SEPTEMBER, state=GENERATED, analysis=None
) -> NutritionReport:
    has_data, summary_status, summary = state
    return NutritionReport(
        establishment_id=establishment_id,
        month=month,
        has_data=has_data,
        analysis={} if analysis is None else analysis,
        reference_profile="nino_7_9",
        summary_status=summary_status,
        summary=summary,
    )


async def save(report: NutritionReport) -> None:
    from app.db.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        session.add(report)
        await session.commit()
