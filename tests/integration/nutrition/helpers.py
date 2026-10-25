import asyncio
from datetime import date, datetime, timezone
from decimal import Decimal

from app.core.interfaces.llm_client import ILlmClient
from app.domain.food_intake import FoodIntakeOriginType, FoodIntakeSource
from app.domain.nutrition_report import SummaryStatus
from app.exceptions.domain_exceptions import LlmClientError
from app.models.establishments.establishment import Establishment
from app.models.food_intakes.food_intake import FoodIntake
from app.models.food_intakes.food_intake_item import FoodIntakeItem
from app.models.nutrition.nutrition_report import NutritionReport

AUGUST = date(2026, 8, 1)
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


async def save_other_establishment() -> Establishment:
    """Insert a second establishment, besides the ``db_establishment`` fixture."""
    from app.db.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        establishment = Establishment(
            name="Otro Centro",
            formatted_address="Calle Otra 456",
            latitude=-34.6037,
            longitude=-58.3816,
            place_id="place-test-002",
            city="Buenos Aires",
            province="Buenos Aires",
        )
        session.add(establishment)
        await session.commit()
        await session.refresh(establishment)
        return establishment


# A month in the past, so the tests do not depend on the date they run.
MARCH = "2026-03"
MARCH_INTAKE = datetime(2026, 3, 15, tzinfo=timezone.utc)


class ReportLlm(ILlmClient):
    """Scripted AI client: records its calls, and can fail or take its time."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.error = False
        self.delay = 0.0

    async def complete(self, *, prompt, response_schema, **kwargs):
        self.calls.append(prompt)
        await asyncio.sleep(self.delay)
        if self.error:
            raise LlmClientError("provider unavailable")
        return dict(SUMMARY)


async def add_intake(establishment_id, responsible_id, when, items) -> None:
    """Save an intake of ``(food_id, quantity)`` items received at ``when``."""
    from app.db.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        session.add(
            FoodIntake(
                establishment_id=establishment_id,
                responsible_id=responsible_id,
                occurred_at=when,
                source=FoodIntakeSource.MANUAL,
                origin_type=FoodIntakeOriginType.OTHER,
                is_recurring=False,
                items=[
                    FoodIntakeItem(food_id=food_id, quantity=Decimal(quantity))
                    for food_id, quantity in items
                ],
            )
        )
        await session.commit()
