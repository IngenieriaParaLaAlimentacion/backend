"""Export a validated SAP reference and synthetic examples for Mobile."""

import argparse
import hashlib
import json
import math
import subprocess
from dataclasses import asdict, replace
from datetime import date, datetime, time, timedelta
from pathlib import Path
from tempfile import NamedTemporaryFile

from app.domain.measurement_assessment import Indicator, StatureMethod
from app.domain.subject import Sex
from app.reference_data.anthropometry import LAMBDA_ZERO_TOLERANCE
from app.reference_data.sap_reference import (
    IndicatorReference,
    ReferenceRow,
    SapRuleset,
    load_ruleset,
)
from app.services.measurements.assessment_service import (
    AssessmentInput,
    evaluate_measurement,
)
from app.utils.dates import ARGENTINA_TZ, completed_months_between

_BIRTH = date(2000, 1, 1)
_ROOT = Path(__file__).resolve().parent.parent


def _day_in_month(month: int) -> date:
    return date(_BIRTH.year + month // 12, month % 12 + 1, _BIRTH.day)


def _input(sex: Sex, day: date) -> AssessmentInput:
    return AssessmentInput(
        sex,
        _BIRTH,
        datetime.combine(day, time(12), tzinfo=ARGENTINA_TZ),
        weight_kg=20,
        height_cm=100,
        stature_method=None,
    )


def _value_at_score(row: ReferenceRow, formula: str, score: float) -> float | None:
    if formula == "standard":
        return row.median + score * row.sigma
    if formula == "lms_extended" and abs(score) > 3:
        sign = math.copysign(1, score)
        outer = _value_at_score(row, "lms", 3 * sign)
        inner = _value_at_score(row, "lms", 2 * sign)
        if outer is None or inner is None:
            return None
        return outer + (abs(score) - 3) * (outer - inner)
    if abs(row.lmbda) < LAMBDA_ZERO_TOLERANCE:
        return row.median * math.exp(row.sigma * score)
    exponent = row.lmbda * row.sigma * score
    if exponent <= -1:
        return None
    return row.median * math.exp(math.log1p(exponent) / row.lmbda)


def _reference_examples(
    reference: IndicatorReference, sex: Sex
) -> list[AssessmentInput]:
    rows = [
        row
        for row in reference.rows
        if row.sex == sex
        and (
            reference.first_month
            <= completed_months_between(_BIRTH, _BIRTH + timedelta(days=row.age))
            <= reference.last_month
            if reference.age_unit == "days"
            else reference.first_month <= row.age <= reference.last_month
        )
    ]
    rows.sort(key=lambda row: row.age)
    examples = []
    for row in (rows[0], rows[-1]) if rows else ():
        day = (
            _BIRTH + timedelta(days=row.age)
            if reference.age_unit == "days"
            else _day_in_month(row.age)
        )
        data = replace(_input(sex, day), stature_method=reference.stature_method)
        scores = {0.0}
        for band in reference.bands:
            if band.lower is not None:
                scores.update((band.lower - 1e-5, band.lower, band.lower + 1e-5))

        for score in sorted(scores):
            value = _value_at_score(row, reference.formula, score)
            if value is None or value <= 0 or not math.isfinite(value):
                continue
            if reference.indicator in (Indicator.WEIGHT_FOR_AGE, Indicator.BMI_FOR_AGE):
                # The synthetic 100 cm stature makes weight numerically equal BMI.
                examples.append(replace(data, weight_kg=value))
            else:
                examples.append(replace(data, height_cm=value))
    return examples


def _examples(ruleset: SapRuleset) -> list[dict]:
    examples = {
        _input(sex, _day_in_month(month))
        for sex in Sex
        for month in (
            0,
            23,
            24,
            ruleset.pediatric_max_month,
            ruleset.pediatric_max_month + 1,
        )
    }
    boundary = _input(Sex.FEMALE, _day_in_month(24))
    examples.add(
        replace(boundary, measured_at=boundary.measured_at - timedelta(hours=13))
    )
    examples.add(replace(boundary, stature_method=StatureMethod.RECUMBENT))
    examples.add(_input(Sex.MALE, _BIRTH - timedelta(days=1)))
    for reference in ruleset.references:
        for sex in Sex:
            examples.update(_reference_examples(reference, sex))

    cases = []
    for data in sorted(
        examples,
        key=lambda item: (
            item.sex,
            item.measured_at,
            item.weight_kg,
            item.height_cm,
            item.stature_method or "",
        ),
    ):
        case = asdict(data)
        case["birth_date"] = data.birth_date.isoformat()
        case["measured_at"] = data.measured_at.isoformat()
        case["assessments"] = [
            asdict(result) for result in evaluate_measurement(data, ruleset)
        ]
        cases.append(case)
    return cases


def export_reference(ruleset: SapRuleset, output: Path, backend_commit: str) -> None:
    """Write a deterministic payload and checksum atomically."""
    payload = {
        "ruleset": ruleset.model_dump(mode="json", by_alias=True),
        "cases": _examples(ruleset),
        "backend_commit": backend_commit,
    }
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()
    payload["sha256"] = hashlib.sha256(canonical).hexdigest()
    output.parent.mkdir(parents=True, exist_ok=True)
    stream = NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=output.parent, delete=False
    )
    temporary = Path(stream.name)
    try:
        with stream:
            json.dump(
                payload,
                stream,
                sort_keys=True,
                indent=2,
                ensure_ascii=False,
                allow_nan=False,
            )
            stream.write("\n")
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> None:
    """Export the explicitly selected reference to a local file."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ruleset-version", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    ruleset = load_ruleset(args.ruleset_version)
    commit = subprocess.check_output(
        ["git", "-C", str(_ROOT), "rev-parse", "HEAD"], text=True
    ).strip()
    export_reference(ruleset, args.output, commit)


if __name__ == "__main__":
    main()
