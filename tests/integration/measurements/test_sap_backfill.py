from uuid import uuid4

from app.db.unit_of_work import UnitOfWork
from app.domain.measurement_assessment import AssessmentStatus, Indicator
from app.domain.user import UserRole
from scripts.backfill_measurement_assessments import backfill
from tests.integration.urls import MEASUREMENTS_URL
from tests.sap_fixtures import synthetic_sap_ruleset


async def test_backfill_can_repeat_without_changing_raw_measurements(
    client, db_subject, db_establishment, make_user_with_role, monkeypatch, capsys
):
    from app.config.settings import settings

    monkeypatch.setattr(settings, "sap_assessment_ruleset", None)
    monkeypatch.setattr(settings, "sap_assessment_visible", False)
    headers, _ = await make_user_with_role(UserRole.ADMIN)
    measurement_id = uuid4()
    body = {
        "id": str(measurement_id),
        "subject_id": str(db_subject.id),
        "establishment_id": str(db_establishment.id),
        "weight_kg": 7.5,
        "height_cm": 70,
        "measured_at": f"{db_subject.birth_date.isoformat()}T15:00:00Z",
    }
    baseline = await client.post(MEASUREMENTS_URL, json=body, headers=headers)
    assert baseline.status_code == 201
    assert baseline.json()["assessments"] is None

    ruleset = synthetic_sap_ruleset()
    assert await backfill(ruleset, apply=False) == 0
    assert "missing_before=1" in capsys.readouterr().out
    assert await backfill(ruleset, apply=True) == 0
    assert "evaluated=1 missing_after=0" in capsys.readouterr().out

    async with UnitOfWork() as uow:
        data = await uow.measurement_assessment_repo.list_for_measurements(
            [measurement_id], ruleset.version
        )

    results = {result.indicator: result for result in data[measurement_id]}
    length = results[Indicator.LENGTH_FOR_AGE]
    assert length.status == AssessmentStatus.INSUFFICIENT_DATA
    assert length.alert is None
    assert results[Indicator.WEIGHT_FOR_AGE].z_score == -2.5

    assert await backfill(ruleset, apply=True) == 0
    assert "evaluated=0 missing_after=0" in capsys.readouterr().out
    replay = await client.post(MEASUREMENTS_URL, json=body, headers=headers)
    assert replay.status_code == 200
    assert replay.json() == baseline.json()

    corrected = await client.patch(
        f"{MEASUREMENTS_URL}/{measurement_id}", json={"weight_kg": 9}, headers=headers
    )
    assert corrected.status_code == 200
    assert await backfill(ruleset, apply=True) == 0
    assert "evaluated=1 missing_after=0" in capsys.readouterr().out
    async with UnitOfWork() as uow:
        data = await uow.measurement_assessment_repo.list_for_measurements(
            [measurement_id], ruleset.version
        )
    results = {result.indicator: result for result in data[measurement_id]}
    assert results[Indicator.WEIGHT_FOR_AGE].z_score == -1
