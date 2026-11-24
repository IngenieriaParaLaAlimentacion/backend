"""Verify the versioned assessment contract with test-only reference data."""

import asyncio
import csv
from io import StringIO
from uuid import uuid4

import pytest

from app.config.settings import settings
from app.domain.user import UserRole
from app.reference_data import sap_reference
from tests.integration.urls import MEASUREMENTS_URL, SUBJECTS_URL
from tests.sap_fixtures import synthetic_sap_ruleset

_ESTABLISHMENTS = "/api/v1/establishments"
_ACTIVITY = "/api/v1/users/me/activity"


@pytest.fixture
def active_assessments(monkeypatch):
    """Enable a synthetic ruleset for these API requests only."""
    ruleset = synthetic_sap_ruleset()
    monkeypatch.setattr(sap_reference, "load_ruleset", lambda version: ruleset)
    monkeypatch.setattr(settings, "sap_assessment_ruleset", ruleset.version)
    monkeypatch.setattr(settings, "sap_assessment_visible", True)


async def _subject(client, headers, dni=30000001, birth_date="2022-06-02"):
    response = await client.post(
        SUBJECTS_URL,
        headers=headers,
        json={
            "dni": dni,
            "name": "Test",
            "last_name": "Subject",
            "sex": "female",
            "birth_date": birth_date,
            "is_rural": False,
            "is_indigenous": False,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _measurement(
    client,
    headers,
    subject_id,
    establishment_id,
    **overrides,
):
    return await client.post(
        MEASUREMENTS_URL,
        headers=headers,
        json={
            "id": str(uuid4()),
            "subject_id": subject_id,
            "establishment_id": str(establishment_id),
            "weight_kg": 7,
            "height_cm": 55,
            "measured_at": "2024-06-02T01:00:00Z",
            "stature_method": "recumbent",
            **overrides,
        },
    )


def _assessments(measurement):
    return {row["indicator"]: row for row in measurement["assessments"]}


def _csv(response):
    assert response.status_code == 200, response.text
    reader = csv.DictReader(
        StringIO(response.content.decode("utf-8-sig")), delimiter=";"
    )
    return reader.fieldnames, list(reader)


async def test_create_replay_and_correct_assessments(
    client, db_establishment, make_user_with_role, active_assessments
):
    admin, _ = await make_user_with_role(UserRole.ADMIN)
    analyst, _ = await make_user_with_role(UserRole.ANALYST)
    subject_id = await _subject(client, admin)

    created = await _measurement(client, admin, subject_id, db_establishment.id)
    assert created.status_code == 201, created.text
    initial = created.json()
    before = _assessments(initial)
    assert before["length_for_age"]["z_score"] == -3
    assert before["weight_for_age"]["alert"]["severity"] == "high"
    assert before["bmi_for_age"]["status"] == "not_applicable"

    replayed = await _measurement(
        client,
        admin,
        subject_id,
        db_establishment.id,
        id=initial["id"],
        weight_kg=20,
    )
    assert replayed.status_code == 200, replayed.text
    assert replayed.json() == initial

    measurement_url = f"{MEASUREMENTS_URL}/{initial['id']}"
    denied = await client.patch(
        measurement_url, headers=analyst, json={"stature_method": None}
    )
    assert denied.status_code == 403
    invalid = await client.patch(
        measurement_url, headers=admin, json={"weight_kg": None}
    )
    assert invalid.status_code == 422

    corrected = await client.patch(
        measurement_url, headers=admin, json={"stature_method": None, "weight_kg": 9}
    )
    assert corrected.status_code == 200, corrected.text
    current = corrected.json()
    assert current["stature_method"] is None
    assert current["weight_kg"] == 9
    assert current["height_cm"] == initial["height_cm"]
    assert current["responsible_id"] == initial["responsible_id"]
    assert _assessments(current)["length_for_age"]["status"] == "insufficient_data"
    assert _assessments(current)["weight_for_age"]["classification"] == "normal"

    evolved = await client.get(
        f"{SUBJECTS_URL}/{subject_id}/measurements/evolution", headers=admin
    )
    assert evolved.status_code == 200, evolved.text
    point = evolved.json()["points"][0]
    assert point["id"] == initial["id"]
    assert point["assessments"] == current["assessments"]
    activity = await client.get(f"{_ACTIVITY}?type=measurement", headers=admin)
    assert activity.status_code == 200, activity.text
    assert (
        activity.json()["items"][0]["measurement"]["assessments"]
        == current["assessments"]
    )


async def test_subject_adjustment_and_upload_agree_on_final_demographics(
    client, db_establishment, make_user_with_role, active_assessments
):
    headers, _ = await make_user_with_role(UserRole.ADMIN)
    subject_id = await _subject(client, headers)
    subject_url = f"{SUBJECTS_URL}/{subject_id}"
    original = await _measurement(client, headers, subject_id, db_establishment.id)
    assert original.status_code == 201, original.text

    changed, uploaded = await asyncio.gather(
        client.patch(
            subject_url,
            headers=headers,
            json={"birth_date": "2020-06-02", "sex": "male"},
        ),
        _measurement(
            client,
            headers,
            subject_id,
            db_establishment.id,
            measured_at="2024-05-02T12:00:00Z",
            stature_method="standing",
            weight_kg=16,
            height_cm=100,
        ),
    )
    assert changed.status_code == 200, changed.text
    assert uploaded.status_code == 201, uploaded.text
    evolution = await client.get(
        f"{subject_url}/measurements/evolution", headers=headers
    )
    assert evolution.status_code == 200, evolution.text
    points = evolution.json()["points"]
    assert len(points) == 2
    for point in points:
        assessments = _assessments(point)
        assert assessments["length_for_age"]["status"] == "not_applicable"
        assert assessments["bmi_for_age"]["status"] == "evaluated"
    assert {point["weight_kg"] for point in points} == {7, 16}


async def test_latest_scope_filter_distribution_and_export(
    client, db_establishment, make_user_with_role, active_assessments
):
    from app.db.database import AsyncSessionLocal
    from app.models.establishments.establishment import Establishment

    headers, _ = await make_user_with_role(UserRole.ADMIN)
    first = await _subject(client, headers)
    second = await _subject(client, headers, dni=30000002)
    local = await _measurement(client, headers, first, db_establishment.id)
    assert local.status_code == 201, local.text
    other_local = await _measurement(
        client,
        headers,
        second,
        db_establishment.id,
        weight_kg=10,
        stature_method=None,
    )
    assert other_local.status_code == 201, other_local.text

    async with AsyncSessionLocal() as session:
        other = Establishment(
            name="Other establishment",
            formatted_address="Other address",
            latitude=-30,
            longitude=-60,
            place_id="test-other",
            city="Other city",
            province="Other province",
        )
        session.add(other)
        await session.commit()
        other_id = other.id

    latest = await _measurement(
        client,
        headers,
        first,
        other_id,
        measured_at="2024-07-03T12:00:00Z",
        weight_kg=16,
        height_cm=100,
        stature_method="standing",
    )
    assert latest.status_code == 201, latest.text

    filters = {"indicator": "length_for_age", "classification": "low"}
    measurements = await client.get(MEASUREMENTS_URL, headers=headers, params=filters)
    assert measurements.status_code == 200, measurements.text
    assert measurements.json()["total"] == 1
    assert measurements.json()["items"][0]["id"] == local.json()["id"]

    subjects = await client.get(SUBJECTS_URL, headers=headers, params=filters)
    assert subjects.status_code == 200, subjects.text
    assert subjects.json()["total"] == 0
    assert len(subjects.json()["assessment_filters"]["indicators"]) == 5

    dashboard = await client.get(
        f"{_ESTABLISHMENTS}/{db_establishment.id}/dashboard", headers=headers
    )
    assert dashboard.status_code == 200, dashboard.text
    summary = dashboard.json()["assessment_summary"]
    assert summary["at_risk_count"] == 1
    assert summary["at_risk_percentage"] == 50
    indicators = {entry["indicator"]: entry for entry in summary["indicators"]}
    assert indicators["length_for_age"]["evaluated_count"] == 1
    assert indicators["weight_for_age"]["evaluated_count"] == 2
    assert indicators["bmi_for_age"]["distribution"] == []

    roster_url = f"{_ESTABLISHMENTS}/{db_establishment.id}/subjects"
    roster = await client.get(roster_url, headers=headers)
    assert roster.status_code == 200, roster.text
    local_first = next(item for item in roster.json()["items"] if item["id"] == first)
    assert local_first["latest_measurement"]["id"] == local.json()["id"]

    baseline = await client.get(
        f"{MEASUREMENTS_URL}/export", headers=headers, params=filters
    )
    upgraded = await client.get(
        f"{MEASUREMENTS_URL}/export",
        headers=headers,
        params={**filters, "assessment_fields": True},
    )
    baseline_columns, baseline_rows = _csv(baseline)
    upgraded_columns, upgraded_rows = _csv(upgraded)
    assert upgraded_columns[: len(baseline_columns)] == baseline_columns
    assert len(upgraded_rows) == len(baseline_rows) == 1
    assert upgraded_rows[0]["Longitud para la edad · Puntaje Z"] == "-3,00"

    roster_export = await client.get(
        f"{roster_url}/export", headers=headers, params={"assessment_fields": True}
    )
    _, roster_rows = _csv(roster_export)
    assert {row["Longitud para la edad · Estado"] for row in roster_rows} == {
        "Evaluado",
        "Sin datos suficientes",
    }

    subject_export = await client.get(
        f"{SUBJECTS_URL}/export",
        headers=headers,
        params={"assessment_fields": True, "indicator": "bmi_for_age"},
    )
    _, subject_rows = _csv(subject_export)
    assert len(subject_rows) == 1
    assert subject_rows[0]["IMC para la edad · Clasificación"] == "normal"


async def test_inactive_assessments_keep_legacy_results_and_reject_filters(
    client, db_establishment, make_user_with_role
):
    headers, _ = await make_user_with_role(UserRole.ADMIN)
    subject_id = await _subject(client, headers)
    created = await _measurement(
        client, headers, subject_id, db_establishment.id, stature_method=None
    )
    assert created.status_code == 201, created.text
    assert created.json()["assessments"] is None
    assert isinstance(created.json()["alerts"], list)

    listing = await client.get(MEASUREMENTS_URL, headers=headers)
    assert listing.status_code == 200
    assert listing.json()["assessment_filters"] is None

    filtered = await client.get(
        MEASUREMENTS_URL, headers=headers, params={"indicator": "length_for_age"}
    )
    assert filtered.status_code == 400
    assert filtered.json()["type"].endswith("/filter-not-applicable")


async def test_listing_keeps_raw_values_and_result_on_the_same_snapshot(
    client, db_establishment, make_user_with_role, active_assessments, monkeypatch
):
    from app.repositories.measurements.measurement_repository import (
        MeasurementRepository,
    )

    headers, _ = await make_user_with_role(UserRole.ADMIN)
    subject_id = await _subject(client, headers)
    created = await _measurement(client, headers, subject_id, db_establishment.id)
    assert created.status_code == 201, created.text
    measurement_id = created.json()["id"]

    original = MeasurementRepository.get_measurement_listing
    corrections = []

    async def list_and_correct(repository, *args, **kwargs):
        rows, total = await original(repository, *args, **kwargs)
        if not corrections:
            corrected = await client.patch(
                f"{MEASUREMENTS_URL}/{measurement_id}",
                headers=headers,
                json={"weight_kg": 9},
            )
            corrections.append(corrected)
        return rows, total

    monkeypatch.setattr(
        MeasurementRepository, "get_measurement_listing", list_and_correct
    )
    during = await client.get(MEASUREMENTS_URL, headers=headers)
    assert during.status_code == 200, during.text
    assert corrections[0].status_code == 200, corrections[0].text
    before = during.json()["items"][0]
    assert before["weight_kg"] == 7
    assert _assessments(before)["weight_for_age"]["classification"] == "low"

    after = await client.get(MEASUREMENTS_URL, headers=headers)
    assert after.status_code == 200, after.text
    updated = after.json()["items"][0]
    assert updated["weight_kg"] == 9
    assert _assessments(updated)["weight_for_age"]["classification"] == "normal"
