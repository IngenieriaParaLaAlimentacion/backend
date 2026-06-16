import math
from datetime import date, datetime

from app.data.who_bmi_for_age import WHO_BMI_LMS
from app.domain.measurement import AlertSeverity, AlertType
from app.domain.subject import Sex


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
    if abs(lamda) < 1e-10:
        return math.log(bmi / median) / sigma
    return ((bmi / median) ** lamda - 1) / (lamda * sigma)


def _child_alerts(
    bmi: float, sex: Sex, months: int
) -> list[tuple[AlertType, AlertSeverity, str]]:
    z = compute_bmi_z_score(bmi, sex, months)
    if z is None:
        return []
    if z < -3:
        return [
            (
                AlertType.SEVERELY_WASTED,
                AlertSeverity.CRITICAL,
                f"BMI-for-age z-score {z:.2f} < -3 SD: severe acute malnutrition"
                f" (emaciación grave).",
            )
        ]
    if z < -2:
        return [
            (
                AlertType.WASTED,
                AlertSeverity.HIGH,
                f"BMI-for-age z-score {z:.2f} < -2 SD: moderate acute malnutrition"
                f" (emaciación).",
            )
        ]
    if z > 3:
        return [
            (
                AlertType.OBESE,
                AlertSeverity.HIGH,
                f"BMI-for-age z-score {z:.2f} > +3 SD: obesity (obesidad).",
            )
        ]
    if z > 2:
        return [
            (
                AlertType.OVERWEIGHT,
                AlertSeverity.MEDIUM,
                f"BMI-for-age z-score {z:.2f} > +2 SD: overweight (sobrepeso).",
            )
        ]
    return []


def _adult_alerts(bmi: float) -> list[tuple[AlertType, AlertSeverity, str]]:
    if bmi < 16:
        return [
            (
                AlertType.SEVERE_UNDERWEIGHT,
                AlertSeverity.CRITICAL,
                f"IMC {bmi:.1f} < 16: delgadez severa.",
            )
        ]
    if bmi < 18.5:
        return [
            (
                AlertType.UNDERWEIGHT,
                AlertSeverity.HIGH,
                f"IMC {bmi:.1f} < 18.5: delgadez.",
            )
        ]
    if bmi >= 30:
        return [
            (
                AlertType.OBESE,
                AlertSeverity.HIGH,
                f"IMC {bmi:.1f} ≥ 30: obesidad.",
            )
        ]
    if bmi >= 25:
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
    if months <= 228:
        return _child_alerts(bmi, sex, months)
    return _adult_alerts(bmi)
