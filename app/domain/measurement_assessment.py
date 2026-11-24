from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.domain.measurement import AlertSeverity


class Indicator(StrEnum):
    """Anthropometric indicators available for assessment."""

    LENGTH_FOR_AGE = "length_for_age"
    WEIGHT_FOR_AGE = "weight_for_age"
    BMI_FOR_AGE = "bmi_for_age"
    HEIGHT_FOR_AGE = "height_for_age"
    ADULT_BMI = "adult_bmi"


class AssessmentStatus(StrEnum):
    """Whether an indicator applies and could be assessed."""

    EVALUATED = "evaluated"
    INSUFFICIENT_DATA = "insufficient_data"
    NOT_APPLICABLE = "not_applicable"


class StatureMethod(StrEnum):
    """How the recorded length or height was measured."""

    RECUMBENT = "recumbent"
    STANDING = "standing"


@dataclass(frozen=True, slots=True)
class AssessmentAlert:
    """An alert produced by an individual indicator."""

    severity: "AlertSeverity"
    detail: str


@dataclass(frozen=True, slots=True)
class Assessment:
    """The outcome for one indicator under a versioned reference."""

    indicator: Indicator
    status: AssessmentStatus
    classification: str | None = None
    z_score: float | None = None
    reference_version: str | None = None
    alert: AssessmentAlert | None = None
