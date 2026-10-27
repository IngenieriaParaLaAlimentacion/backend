import asyncio
import uuid
from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError

from app.domain.nutrition_report import NutritionReportListingParams, SummaryStatus
from tests.integration.nutrition_reports.helpers import (
    GENERATED,
    NOT_APPLICABLE,
    OCTOBER,
    SEPTEMBER,
    SUMMARY,
    UNAVAILABLE,
    make_report,
    save,
    save_other_establishment,
)

pytestmark = pytest.mark.usefixtures("app")


@pytest.mark.parametrize("state", [GENERATED, UNAVAILABLE, NOT_APPLICABLE])
async def test_report_in_each_valid_state_is_saved(state, db_establishment):
    await save(make_report(db_establishment.id, state=state))


@pytest.mark.parametrize(
    "state",
    [
        (True, SummaryStatus.GENERATED, None),
        (True, SummaryStatus.UNAVAILABLE, SUMMARY),
        (False, SummaryStatus.GENERATED, SUMMARY),
        (False, SummaryStatus.UNAVAILABLE, None),
        (True, SummaryStatus.NOT_APPLICABLE, None),
    ],
    ids=[
        "generated-without-summary",
        "summary-without-being-generated",
        "generated-without-data",
        "unavailable-without-data",
        "not-applicable-with-data",
    ],
)
async def test_report_with_inconsistent_summary_is_rejected(state, db_establishment):
    with pytest.raises(IntegrityError):
        await save(make_report(db_establishment.id, state=state))


async def test_month_must_be_the_first_day(db_establishment):
    with pytest.raises(IntegrityError):
        await save(make_report(db_establishment.id, month=date(2026, 9, 15)))


async def test_second_report_for_the_same_month_is_rejected(db_establishment):
    await save(make_report(db_establishment.id))

    with pytest.raises(IntegrityError):
        await save(make_report(db_establishment.id))


async def test_get_by_month_returns_only_that_months_report(db_establishment):
    from app.db.database import AsyncSessionLocal
    from app.repositories.nutrition_reports.nutrition_report_repository import (
        NutritionReportRepository,
    )

    report = make_report(db_establishment.id)
    await save(report)

    async with AsyncSessionLocal() as session:
        repo = NutritionReportRepository(session)
        found = await repo.get_by_month(db_establishment.id, SEPTEMBER)
        assert found is not None and found.id == report.id
        assert await repo.get_by_month(db_establishment.id, OCTOBER) is None


async def test_lock_makes_a_second_transaction_wait_until_the_first_ends(app):
    from app.db.database import AsyncSessionLocal
    from app.repositories.nutrition_reports.nutrition_report_repository import (
        NutritionReportRepository,
    )

    establishment_id = uuid.uuid4()
    async with AsyncSessionLocal() as first, AsyncSessionLocal() as second:
        await NutritionReportRepository(first).lock(establishment_id, SEPTEMBER)
        waiting = asyncio.create_task(
            NutritionReportRepository(second).lock(establishment_id, SEPTEMBER)
        )

        await asyncio.sleep(0.3)
        assert not waiting.done()

        await first.commit()
        await asyncio.wait_for(waiting, timeout=5)


async def test_listing_only_includes_the_establishments_own_reports(db_establishment):
    from app.db.database import AsyncSessionLocal
    from app.repositories.nutrition_reports.nutrition_report_repository import (
        NutritionReportRepository,
    )

    other = await save_other_establishment()
    await save(make_report(db_establishment.id))
    await save(make_report(other.id, month=OCTOBER))

    async with AsyncSessionLocal() as session:
        reports, total = await NutritionReportRepository(session).list_by_establishment(
            db_establishment.id,
            limit=20,
            offset=0,
            params=NutritionReportListingParams(),
        )

    assert [report.month for report in reports] == [SEPTEMBER]
    assert total == 1
