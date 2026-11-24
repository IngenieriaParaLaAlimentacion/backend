import hashlib
import json
from dataclasses import replace
from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from app.config.settings import Settings
from app.domain.measurement import AlertSeverity
from app.domain.measurement_assessment import AssessmentStatus, Indicator, StatureMethod
from app.domain.subject import Sex
from app.reference_data.sap_reference import SapRuleset
from app.services.measurements.assessment_service import (
    AssessmentInput,
    evaluate_measurement,
)
from scripts.export_anthropometry_reference import export_reference
from tests.sap_fixtures import synthetic_sap_ruleset


@pytest.fixture(scope="module")
def ruleset():
    return synthetic_sap_ruleset()


@pytest.fixture
def data():
    return AssessmentInput(
        sex=Sex.FEMALE,
        birth_date=date(2024, 6, 10),
        measured_at=datetime(2026, 6, 10, 2, 59, tzinfo=UTC),
        weight_kg=7.5,
        height_cm=70,
        stature_method=None,
    )


def indexed(data, ruleset):
    return {result.indicator: result for result in evaluate_measurement(data, ruleset)}


def test_measurement_date_and_missing_posture(data, ruleset):
    results = indexed(data, ruleset)
    assert (
        results[Indicator.LENGTH_FOR_AGE].status == AssessmentStatus.INSUFFICIENT_DATA
    )
    assert results[Indicator.LENGTH_FOR_AGE].alert is None
    assert results[Indicator.WEIGHT_FOR_AGE].classification == "low"
    assert results[Indicator.WEIGHT_FOR_AGE].z_score == -2.5
    assert results[Indicator.WEIGHT_FOR_AGE].alert.severity == AlertSeverity.HIGH
    assert results[Indicator.BMI_FOR_AGE].status == AssessmentStatus.NOT_APPLICABLE

    next_day = replace(data, measured_at=data.measured_at.replace(hour=3, minute=0))
    results = indexed(next_day, ruleset)
    assert results[Indicator.LENGTH_FOR_AGE].status == AssessmentStatus.NOT_APPLICABLE
    assert results[Indicator.BMI_FOR_AGE].status == AssessmentStatus.EVALUATED
    assert results[Indicator.HEIGHT_FOR_AGE].status == AssessmentStatus.EVALUATED

    same_instant = replace(
        next_day, measured_at=datetime.fromisoformat("2026-06-10T00:00:00-03:00")
    )
    assert indexed(same_instant, ruleset) == results


@pytest.mark.parametrize(
    ("weight", "expected"),
    [(7.999, "low"), (8, "normal"), (11.999, "normal"), (12, "high")],
)
def test_score_cutoffs_use_unrounded_score(data, ruleset, weight, expected):
    result = indexed(replace(data, weight_kg=weight), ruleset)[Indicator.WEIGHT_FOR_AGE]
    assert result.classification == expected
    assert (result.alert is None) == (expected == "normal")


def test_adjustment_leaves_raw_stature_intact(data, ruleset):
    standing_length = replace(data, stature_method=StatureMethod.STANDING)
    result = indexed(standing_length, ruleset)[Indicator.LENGTH_FOR_AGE]
    assert result.z_score == 0.1
    assert standing_length.height_cm == data.height_cm


def test_prebirth_and_adult_semantics(data, ruleset):
    before = replace(data, birth_date=date(2026, 6, 10))
    assert {result.status for result in indexed(before, ruleset).values()} == {
        AssessmentStatus.INSUFFICIENT_DATA
    }

    adult = replace(data, birth_date=date(2000, 6, 10), weight_kg=30, height_cm=100)
    results = indexed(adult, ruleset)
    result = results[Indicator.ADULT_BMI]
    assert result.classification == "obese"
    assert result.z_score is None
    assert result.alert.severity == AlertSeverity.HIGH
    assert results[Indicator.BMI_FOR_AGE].status == AssessmentStatus.NOT_APPLICABLE


def test_reject_missing_bundle_and_visible_without_version():
    with pytest.raises(ValidationError, match="not installed"):
        Settings(sap_assessment_ruleset="not-installed")
    with pytest.raises(ValidationError, match="require a ruleset"):
        Settings(sap_assessment_visible=True, sap_assessment_ruleset="")


def test_reference_validation_rejects_ambiguous_bands(ruleset):
    raw = ruleset.model_dump(mode="json", by_alias=True)
    raw["references"][0]["bands"][0]["include_upper"] = True
    with pytest.raises(ValidationError, match="unique inclusive boundary"):
        SapRuleset.model_validate(raw)


@pytest.mark.parametrize("age_unit", ["months", "days"])
def test_reference_validation_rejects_truncated_tables(ruleset, age_unit):
    raw = ruleset.model_dump(mode="json", by_alias=True)
    table = raw["references"][0]
    table["age_unit"] = age_unit
    if age_unit == "months":
        table["last_month"] = 22
    else:
        table["first_day"] = 0
        table["last_day"] = 730
    with pytest.raises(ValidationError, match="do not cover"):
        SapRuleset.model_validate(raw)


def test_export_is_repeatable_and_contains_expected_results(ruleset, tmp_path):
    output = tmp_path / "reference.json"
    export_reference(ruleset, output, "test-commit")
    rendered = output.read_bytes()
    export_reference(ruleset, output, "test-commit")
    assert output.read_bytes() == rendered

    payload = json.loads(rendered)
    sha256 = payload.pop("sha256")
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    assert hashlib.sha256(canonical).hexdigest() == sha256
    assert payload["ruleset"]["version"] == ruleset.version
    assert all(len(case["assessments"]) == len(Indicator) for case in payload["cases"])
    assert any(
        assessment["classification"] == "low"
        for case in payload["cases"]
        for assessment in case["assessments"]
    )
