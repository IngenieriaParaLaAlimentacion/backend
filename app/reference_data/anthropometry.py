import math
from datetime import date, datetime

from app.domain.measurement import AlertSeverity, AlertType
from app.domain.subject import Sex
from app.reference_data.who_bmi_for_age import WHO_BMI_LMS

# The LMS z-score formula divides by L, which is undefined at L=0. WHO's LMS
# method defines a separate log-based formula for that case. L is a fitted
# float that lands extremely close to (but essentially never exactly at)
# zero, so we treat anything within this tolerance as the L=0 case.
LAMBDA_ZERO_TOLERANCE = 1e-10

# WHO BMI-for-age reference tables (WHO_BMI_LMS) only cover ages 0-19 years.
# Past that, WHO switches from age/sex-adjusted z-scores to fixed adult BMI
# cutoffs (see BMI_* constants below).
MAX_CHILD_AGE_MONTHS = 19 * 12  # 228

# WHO BMI-for-age z-score cutoffs (ages 0-19y).
# https://www.who.int/tools/growth-reference-data-for-5to19-years/indicators/bmi-for-age
Z_SCORE_SEVERE_WASTING = -3  # z < -3 SD: severe acute malnutrition
Z_SCORE_WASTING = -2  # z < -2 SD: moderate acute malnutrition
Z_SCORE_OVERWEIGHT = 2  # z > +2 SD: overweight
Z_SCORE_OBESE = 3  # z > +3 SD: obesity

# WHO adult (>=19y) BMI classification cutoffs, in kg/m^2.
# https://www.who.int/data/gho/data/themes/topics/topic-details/GHO/body-mass-index
BMI_SEVERE_UNDERWEIGHT = 16.0
BMI_UNDERWEIGHT = 18.5
BMI_OVERWEIGHT = 25.0
BMI_OBESE = 30.0


def age_in_months(birth_date: date, measured_at: datetime) -> int:
    """Return completed months between birth_date and the measurement date."""
    ref = measured_at.date()
    months = (ref.year - birth_date.year) * 12 + (ref.month - birth_date.month)
    if ref.day < birth_date.day:
        months -= 1
    return max(0, months)


def compute_bmi_z_score(bmi: float, sex: Sex, months: int) -> float | None:
    """Return the WHO BMI-for-age z-score, or None if LMS data is unavailable
    for this age/sex."""
    lms = WHO_BMI_LMS.get((sex.value, months))
    if lms is None:
        return None
    lamda, median, sigma = lms
    if abs(lamda) < LAMBDA_ZERO_TOLERANCE:
        return math.log(bmi / median) / sigma
    return ((bmi / median) ** lamda - 1) / (lamda * sigma)


def _child_alerts(
    bmi: float, sex: Sex, months: int
) -> list[tuple[AlertType, AlertSeverity, str]]:
    z = compute_bmi_z_score(bmi, sex, months)
    if z is None:
        return []
    if z < Z_SCORE_SEVERE_WASTING:
        return [
            (
                AlertType.SEVERELY_WASTED,
                AlertSeverity.CRITICAL,
                f"BMI-for-age z-score {z:.2f} < -3 SD: severe acute malnutrition"
                f" (emaciación grave).",
            )
        ]
    if z < Z_SCORE_WASTING:
        return [
            (
                AlertType.WASTED,
                AlertSeverity.HIGH,
                f"BMI-for-age z-score {z:.2f} < -2 SD: moderate acute malnutrition"
                f" (emaciación).",
            )
        ]
    if z > Z_SCORE_OBESE:
        return [
            (
                AlertType.OBESE,
                AlertSeverity.HIGH,
                f"BMI-for-age z-score {z:.2f} > +3 SD: obesity (obesidad).",
            )
        ]
    if z > Z_SCORE_OVERWEIGHT:
        return [
            (
                AlertType.OVERWEIGHT,
                AlertSeverity.MEDIUM,
                f"BMI-for-age z-score {z:.2f} > +2 SD: overweight (sobrepeso).",
            )
        ]
    return []


def _adult_alerts(bmi: float) -> list[tuple[AlertType, AlertSeverity, str]]:
    if bmi < BMI_SEVERE_UNDERWEIGHT:
        return [
            (
                AlertType.SEVERE_UNDERWEIGHT,
                AlertSeverity.CRITICAL,
                f"IMC {bmi:.1f} < 16: delgadez severa.",
            )
        ]
    if bmi < BMI_UNDERWEIGHT:
        return [
            (
                AlertType.UNDERWEIGHT,
                AlertSeverity.HIGH,
                f"IMC {bmi:.1f} < 18.5: delgadez.",
            )
        ]
    if bmi >= BMI_OBESE:
        return [
            (
                AlertType.OBESE,
                AlertSeverity.HIGH,
                f"IMC {bmi:.1f} ≥ 30: obesidad.",
            )
        ]
    if bmi >= BMI_OVERWEIGHT:
        return [
            (
                AlertType.OVERWEIGHT,
                AlertSeverity.MEDIUM,
                f"IMC {bmi:.1f} ≥ 25: sobrepeso.",
            )
        ]
    return []


def evaluate_alerts(
    bmi: float,
    sex: Sex,
    birth_date: date,
    measured_at: datetime,
) -> list[tuple[AlertType, AlertSeverity, str]]:
    """Return (alert_type, severity, detail) tuples for the given measurement.

    Returns an empty list when no nutritional risk is detected or when
    WHO reference data is unavailable for the subject's age.
    """
    months = age_in_months(birth_date, measured_at)
    if months <= MAX_CHILD_AGE_MONTHS:
        return _child_alerts(bmi, sex, months)
    return _adult_alerts(bmi)
