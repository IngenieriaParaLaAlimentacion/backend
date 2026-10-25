import uuid

import pytest

from app.domain.nutrition import PrioritizedNutrient
from app.models.establishments.establishment import Establishment
from app.schemas.nutrition.nutrition_report_schema import (
    NutritionReportAnalysis,
    ReportFoodWithoutConversion,
    ReportNutrient,
)
from tests.integration.nutrition.helpers import (
    GENERATED,
    NOT_APPLICABLE,
    UNAVAILABLE,
    make_report,
    save,
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
    return f"{ROOT}/establishments/{establishment_id}/nutrition-report/{month}"


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
    from app.db.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        other = Establishment(
            name="Otro Centro",
            formatted_address="Calle Otra 456",
            latitude=-34.6037,
            longitude=-58.3816,
            place_id="place-test-002",
            city="Buenos Aires",
            province="Buenos Aires",
        )
        session.add(other)
        await session.commit()
        await session.refresh(other)
    await save(make_report(other.id))

    response = await client.get(report_url(db_establishment.id), headers=admin_headers)

    assert response.status_code == 404


async def test_unknown_establishment_returns_404(client, admin_headers):
    response = await client.get(report_url(uuid.uuid4()), headers=admin_headers)

    assert response.status_code == 404


async def test_field_worker_returns_403(client, field_worker_headers, db_establishment):
    await save(make_report(db_establishment.id))

    response = await client.get(
        report_url(db_establishment.id), headers=field_worker_headers
    )

    assert response.status_code == 403
