from collections import defaultdict
from functools import cached_property, lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator

from app.domain.measurement import AlertSeverity, AlertType
from app.domain.measurement_assessment import Indicator, StatureMethod
from app.domain.subject import Sex

_RULESET_ROOT = Path(__file__).parent / "sap"
RulesetVersion = Annotated[
    str, Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$", max_length=128)
]
ADULT_CLASSIFICATIONS = (
    AlertType.SEVERE_UNDERWEIGHT.value,
    AlertType.UNDERWEIGHT.value,
    "normal",
    AlertType.OVERWEIGHT.value,
    AlertType.OBESE.value,
)


class _ReferenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ScoreBand(_ReferenceModel):
    """Classification and alert for an interval of Z-scores."""

    lower: FiniteFloat | None
    upper: FiniteFloat | None
    include_lower: bool
    include_upper: bool
    classification: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=64)
    severity: AlertSeverity | None

    @model_validator(mode="after")
    def validate_bounds(self):
        """Require a positive-width band and meaningful bound flags."""
        if self.lower is not None and self.upper is not None:
            if self.lower >= self.upper:
                raise ValueError("score band lower bound must precede upper bound")
        if (self.lower is None and self.include_lower) or (
            self.upper is None and self.include_upper
        ):
            raise ValueError("unbounded score limits cannot be inclusive")
        return self

    def contains(self, score: float) -> bool:
        """Check both interval endpoints without rounding the score."""
        lower = self.lower
        upper = self.upper
        return (
            lower is None or score > lower or (self.include_lower and score == lower)
        ) and (
            upper is None or score < upper or (self.include_upper and score == upper)
        )


class ReferenceRow(_ReferenceModel):
    """Numeric parameters for one sex and age."""

    sex: Sex
    age: int = Field(ge=0)
    lmbda: FiniteFloat = Field(alias="lambda")
    median: FiniteFloat = Field(gt=0)
    sigma: FiniteFloat = Field(gt=0)


class IndicatorReference(_ReferenceModel):
    """One sourced reference and classification table for an age interval."""

    indicator: Indicator
    reference_version: str = Field(min_length=1, max_length=128)
    source: str = Field(min_length=1)
    first_month: int = Field(ge=0)
    last_month: int = Field(ge=0)
    age_unit: Literal["days", "months"]
    first_day: int | None = Field(default=None, ge=0)
    last_day: int | None = Field(default=None, ge=0)
    formula: Literal["lms", "lms_extended", "standard"]
    stature_method: StatureMethod | None
    alternate_method_offset_cm: FiniteFloat | None
    bands: tuple[ScoreBand, ...] = Field(min_length=1)
    rows: tuple[ReferenceRow, ...] = Field(min_length=1)

    @cached_property
    def rows_by_age(self) -> dict[tuple[Sex, int], ReferenceRow]:
        """Index the exact source rows by the source-defined age unit."""
        return {(row.sex, row.age): row for row in self.rows}

    @model_validator(mode="after")
    def verify_table(self):
        """Reject conflicting reference rows or ambiguous score intervals."""
        if self.first_month > self.last_month:
            raise ValueError("reference age interval is reversed")

        required_method = {
            Indicator.LENGTH_FOR_AGE: StatureMethod.RECUMBENT,
            Indicator.HEIGHT_FOR_AGE: StatureMethod.STANDING,
        }.get(self.indicator)
        if self.stature_method != required_method:
            raise ValueError("reference uses an invalid stature method")
        if self.alternate_method_offset_cm is not None and required_method is None:
            raise ValueError("only stature references can specify a posture offset")

        if self.age_unit == "days":
            if (
                self.first_day is None
                or self.last_day is None
                or self.first_day > self.last_day
            ):
                raise ValueError("daily references require an ordered source day range")
            first_age, last_age = self.first_day, self.last_day
        else:
            if self.first_day is not None or self.last_day is not None:
                raise ValueError("only daily references can specify a source day range")
            first_age, last_age = self.first_month, self.last_month

        if len(self.rows_by_age) != len(self.rows):
            raise ValueError("duplicate sex and age in reference rows")
        for sex in Sex:
            ages = sorted(age for row_sex, age in self.rows_by_age if row_sex == sex)
            if not ages or len(ages) != ages[-1] - ages[0] + 1:
                raise ValueError("reference rows must be contiguous for each sex")
            if ages[0] > first_age or ages[-1] < last_age:
                raise ValueError("reference rows do not cover the declared age range")

        if self.formula == "lms_extended" and any(
            3 * abs(row.lmbda) * row.sigma >= 1 for row in self.rows
        ):
            raise ValueError("extended LMS requires finite values at ±3 SD")
        if self.bands[0].lower is not None or self.bands[-1].upper is not None:
            raise ValueError("score bands must cover both unbounded tails")
        for left, right in zip(self.bands, self.bands[1:], strict=False):
            if (
                left.upper is None
                or right.lower != left.upper
                or left.include_upper == right.include_lower
            ):
                raise ValueError("score bands must meet at a unique inclusive boundary")
        return self


class SapRuleset(_ReferenceModel):
    """An immutable set of sourced reference tables and classification rules."""

    schema_version: Literal[1]
    version: RulesetVersion
    pediatric_max_month: int = Field(ge=24)
    references: tuple[IndicatorReference, ...]

    @cached_property
    def references_by_indicator(self) -> dict[Indicator, list[IndicatorReference]]:
        """Group the references used to select tables by indicator and age."""
        grouped = defaultdict(list)
        for reference in self.references:
            grouped[reference.indicator].append(reference)
        return grouped

    @model_validator(mode="after")
    def verify_indicator_coverage(self):
        """Check the required indicators and their allowed clinical age bands."""
        expected = {
            Indicator.LENGTH_FOR_AGE: (0, 23),
            Indicator.WEIGHT_FOR_AGE: (0, 23),
            Indicator.BMI_FOR_AGE: (24, self.pediatric_max_month),
            Indicator.HEIGHT_FOR_AGE: (24, self.pediatric_max_month),
        }
        if self.references_by_indicator.keys() != expected.keys():
            raise ValueError("reference set must contain all four pediatric indicators")
        for indicator, (first, last) in expected.items():
            references = sorted(
                self.references_by_indicator[indicator],
                key=lambda reference: reference.first_month,
            )
            next_month = first
            for reference in references:
                if reference.first_month != next_month or reference.last_month > last:
                    raise ValueError(
                        f"reference age ranges are not contiguous for {indicator}"
                    )
                next_month = reference.last_month + 1
            if next_month != last + 1:
                raise ValueError(f"reference age ranges do not cover {indicator}")
        return self

    def reference_for(
        self, indicator: Indicator, months: int
    ) -> IndicatorReference | None:
        """Find the unique table applicable to the indicator and age."""
        for reference in self.references_by_indicator.get(indicator, ()):
            if reference.first_month <= months <= reference.last_month:
                return reference
        return None

    def classifications(self, indicator: Indicator) -> tuple[str, ...]:
        """Return filter choices in configured band order."""
        if indicator == Indicator.ADULT_BMI:
            return ADULT_CLASSIFICATIONS
        return tuple(
            dict.fromkeys(
                band.classification
                for reference in self.references_by_indicator.get(indicator, ())
                for band in reference.bands
            )
        )


@lru_cache(maxsize=8)
def load_ruleset(version: str) -> SapRuleset:
    """Read a packaged SAP ruleset by version and check its identity."""
    from pydantic import TypeAdapter

    TypeAdapter(RulesetVersion).validate_python(version)
    path = _RULESET_ROOT / version / "reference.json"
    try:
        ruleset = SapRuleset.model_validate_json(path.read_bytes())
    except OSError as exc:
        raise ValueError(f"SAP ruleset {version!r} is not installed") from exc
    if ruleset.version != version:
        raise ValueError("SAP ruleset manifest version does not match its directory")
    return ruleset


def configured_ruleset() -> SapRuleset | None:
    """Return the configured target for database writes."""
    from app.config.settings import settings

    version = settings.sap_assessment_ruleset
    return load_ruleset(version) if version is not None else None


def visible_ruleset() -> SapRuleset | None:
    """Return the version exposed to API consumers."""
    from app.config.settings import settings

    return configured_ruleset() if settings.sap_assessment_visible else None
