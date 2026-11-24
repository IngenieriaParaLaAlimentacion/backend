import math
from dataclasses import dataclass
from datetime import UTC, date, datetime

from app.core.interfaces.unit_of_work import IUnitOfWork
from app.domain.measurement_assessment import (
    Assessment,
    AssessmentAlert,
    AssessmentStatus,
    Indicator,
    StatureMethod,
)
from app.domain.subject import Sex
from app.models.measurements.measurement import Measurement
from app.models.subjects.subject import Subject
from app.reference_data.anthropometry import LAMBDA_ZERO_TOLERANCE, _adult_alerts
from app.reference_data.sap_reference import (
    IndicatorReference,
    ReferenceRow,
    SapRuleset,
)
from app.utils.dates import ARGENTINA_TZ, completed_months_between


@dataclass(frozen=True, slots=True)
class AssessmentInput:
    """Raw measurement and demographics for an anthropometric assessment."""

    sex: Sex
    birth_date: date
    measured_at: datetime
    weight_kg: float
    height_cm: float
    stature_method: StatureMethod | None

    @property
    def bmi(self) -> float:
        """Calculate BMI from the original, unrounded values."""
        return self.weight_kg / (self.height_cm / 100) ** 2


_INFANT_INDICATORS = (Indicator.LENGTH_FOR_AGE, Indicator.WEIGHT_FOR_AGE)
_CHILD_INDICATORS = (Indicator.BMI_FOR_AGE, Indicator.HEIGHT_FOR_AGE)


def _reference_value(row: ReferenceRow, score: float) -> float:
    if abs(row.lmbda) < LAMBDA_ZERO_TOLERANCE:
        return row.median * math.exp(score * row.sigma)
    return row.median * math.exp(math.log1p(row.lmbda * row.sigma * score) / row.lmbda)


def _z_score(value: float, row: ReferenceRow, reference: IndicatorReference) -> float:
    if reference.formula == "standard":
        return (value - row.median) / row.sigma

    ratio_log = math.log(value / row.median)
    if abs(row.lmbda) < LAMBDA_ZERO_TOLERANCE:
        score = ratio_log / row.sigma
    else:
        score = math.expm1(row.lmbda * ratio_log) / (row.lmbda * row.sigma)

    if reference.formula != "lms_extended" or -3 <= score <= 3:
        return score

    if score > 3:
        bound = _reference_value(row, 3)
        return 3 + (value - bound) / (bound - _reference_value(row, 2))

    bound = _reference_value(row, -3)
    return -3 + (value - bound) / (_reference_value(row, -2) - bound)


def _indicator_value(
    data: AssessmentInput, reference: IndicatorReference
) -> float | None:
    if reference.indicator == Indicator.WEIGHT_FOR_AGE:
        return data.weight_kg
    if reference.indicator == Indicator.BMI_FOR_AGE:
        return data.bmi
    if data.stature_method == reference.stature_method:
        return data.height_cm
    if data.stature_method is None:
        if reference.indicator == Indicator.HEIGHT_FOR_AGE:
            return data.height_cm
        return None
    offset = reference.alternate_method_offset_cm
    return None if offset is None else data.height_cm + offset


def _evaluate_pediatric(
    indicator: Indicator,
    data: AssessmentInput,
    measured_day: date,
    months: int,
    ruleset: SapRuleset,
) -> Assessment:
    reference = ruleset.reference_for(indicator, months)
    if reference is None:
        return Assessment(indicator, AssessmentStatus.INSUFFICIENT_DATA)
    missing = Assessment(
        indicator,
        AssessmentStatus.INSUFFICIENT_DATA,
        reference_version=reference.reference_version,
    )
    if indicator == Indicator.BMI_FOR_AGE and data.height_cm <= 0:
        return missing
    value = _indicator_value(data, reference)
    age = (
        (measured_day - data.birth_date).days
        if reference.age_unit == "days"
        else months
    )
    row = reference.rows_by_age.get((data.sex, age))
    if row is None or value is None or not math.isfinite(value) or value <= 0:
        return missing

    score = _z_score(value, row, reference)
    if not math.isfinite(score):
        return missing
    band = next(band for band in reference.bands if band.contains(score))
    return Assessment(
        indicator,
        AssessmentStatus.EVALUATED,
        classification=band.classification,
        z_score=score,
        reference_version=reference.reference_version,
        alert=(
            AssessmentAlert(band.severity, f"{indicator.value}: Z {score:.2f}")
            if band.severity is not None
            else None
        ),
    )


def _evaluate_adult(data: AssessmentInput) -> Assessment:
    indicator = Indicator.ADULT_BMI
    if data.height_cm <= 0 or not math.isfinite(data.bmi) or data.bmi <= 0:
        return Assessment(indicator, AssessmentStatus.INSUFFICIENT_DATA)
    alerts = _adult_alerts(data.bmi)
    classification = "normal"
    alert = None
    if alerts:
        alert_type, severity, detail = alerts[0]
        classification = alert_type.value
        alert = AssessmentAlert(severity, detail)
    return Assessment(
        indicator,
        AssessmentStatus.EVALUATED,
        classification=classification,
        reference_version="who-adult-bmi",
        alert=alert,
    )


def evaluate_measurement(
    data: AssessmentInput, ruleset: SapRuleset
) -> tuple[Assessment, ...]:
    """Evaluate each indicator against the selected reference version."""
    measured_at = data.measured_at
    if measured_at.tzinfo is None:
        measured_at = measured_at.replace(tzinfo=UTC)
    measured_day = measured_at.astimezone(ARGENTINA_TZ).date()
    if measured_day < data.birth_date:
        return tuple(
            Assessment(indicator, AssessmentStatus.INSUFFICIENT_DATA)
            for indicator in Indicator
        )
    months = completed_months_between(data.birth_date, measured_day)
    if months < 24:
        applicable = _INFANT_INDICATORS
    elif months <= ruleset.pediatric_max_month:
        applicable = _CHILD_INDICATORS
    else:
        applicable = (Indicator.ADULT_BMI,)

    results = []
    for indicator in Indicator:
        if indicator not in applicable:
            result = Assessment(indicator, AssessmentStatus.NOT_APPLICABLE)
        elif indicator == Indicator.ADULT_BMI:
            result = _evaluate_adult(data)
        else:
            result = _evaluate_pediatric(indicator, data, measured_day, months, ruleset)
        results.append(result)
    return tuple(results)


async def persist_assessments(
    uow: IUnitOfWork,
    measurement: Measurement,
    subject: Subject,
    ruleset: SapRuleset,
) -> tuple[Assessment, ...]:
    """Upsert the complete result in the caller's measurement transaction."""
    data = AssessmentInput(
        sex=Sex(subject.sex),
        birth_date=subject.birth_date,
        measured_at=measurement.measured_at,
        weight_kg=measurement.weight_kg,
        height_cm=measurement.height_cm,
        stature_method=measurement.stature_method,
    )
    results = evaluate_measurement(data, ruleset)
    await uow.measurement_assessment_repo.upsert(
        measurement.id, ruleset.version, results
    )
    return results
