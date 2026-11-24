from datetime import date, datetime, timezone
from typing import Annotated, Generic, Self, TypeVar
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)

from app.domain.common_domains import normalize_optional_str
from app.domain.measurement import AlertSeverity, AlertType
from app.domain.measurement_assessment import AssessmentStatus, Indicator, StatureMethod
from app.domain.subject import Sex
from app.schemas.common import IdentifierRefSchema
from app.schemas.pagination import PaginatedResponse
from app.schemas.types import ClientGeneratedId, RoundedBmi
from app.utils.dates import validate_not_future_datetime

WeightKg = Annotated[float, Field(gt=0.5, le=300, description="Weight in kilograms.")]
HeightCm = Annotated[
    float, Field(gt=20.0, le=250.0, description="Height in centimetres.")
]


# -- Request --


class MeasurementRequest(BaseModel):
    id: ClientGeneratedId
    subject_id: UUID
    establishment_id: UUID
    weight_kg: WeightKg
    height_cm: HeightCm
    measured_at: datetime
    stature_method: StatureMethod | None = None
    observation: str | None = Field(default=None, max_length=500)

    @field_validator("observation", mode="before")
    @classmethod
    def normalize_observation(cls, value):
        """Trim optional observation text and collapse blank input."""
        return normalize_optional_str(value) if isinstance(value, str) else value

    _check_measured_at = field_validator("measured_at")(validate_not_future_datetime)


class MeasurementCorrectionRequest(BaseModel):
    """Clinical data that can be corrected on a stored measurement."""

    model_config = ConfigDict(extra="forbid")

    weight_kg: WeightKg | None = None
    height_cm: HeightCm | None = None
    measured_at: datetime | None = None
    stature_method: StatureMethod | None = None

    @field_validator("weight_kg", "height_cm", "measured_at", mode="before")
    @classmethod
    def reject_null_values(cls, value):
        """Omit values that should stay unchanged."""
        if value is None:
            raise ValueError("Explicit null is only allowed for stature_method")
        return value

    @field_validator("measured_at")
    @classmethod
    def validate_measurement_time(cls, value: datetime) -> datetime:
        """Validate and normalize a supplied correction timestamp."""
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return validate_not_future_datetime(value)


# -- Response --


class AlertResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    alert_type: AlertType
    severity: AlertSeverity
    detail: str


class AssessmentAlertResponse(BaseModel):
    """Alert associated with a single indicator."""

    model_config = ConfigDict(from_attributes=True)

    severity: AlertSeverity
    detail: str


class AssessmentResponse(BaseModel):
    """A versioned classification and alert for one indicator."""

    model_config = ConfigDict(from_attributes=True)

    indicator: Indicator
    status: AssessmentStatus
    classification: str | None
    z_score: float | None
    reference_version: str | None
    alert: AssessmentAlertResponse | None


class AssessmentFilterOptionResponse(BaseModel):
    """Available classifications for one filterable indicator."""

    model_config = ConfigDict(from_attributes=True)

    indicator: Indicator
    classifications: list[str]


class AssessmentFiltersResponse(BaseModel):
    """Filter options for the active assessment ruleset."""

    indicators: list[AssessmentFilterOptionResponse]

    @classmethod
    def for_options(
        cls, options: dict[Indicator, tuple[str, ...]] | None
    ) -> Self | None:
        """Convert the visible ruleset's options to listing metadata."""
        if options is None:
            return None
        return cls(
            indicators=[
                AssessmentFilterOptionResponse(
                    indicator=indicator, classifications=list(classifications)
                )
                for indicator, classifications in options.items()
            ]
        )


ListingItem = TypeVar("ListingItem")


class AssessmentPaginatedResponse(PaginatedResponse[ListingItem], Generic[ListingItem]):
    """A listing with optional assessment-filter metadata."""

    assessment_filters: AssessmentFiltersResponse | None = None


class MeasurementSnapshotBase(BaseModel):
    """A clinical reading of a measurement, shared by snapshots."""

    model_config = ConfigDict(from_attributes=True)

    measured_at: datetime
    weight_kg: float
    height_cm: float
    bmi: RoundedBmi
    alerts: list[AlertResponse]
    observation: str | None = None
    stature_method: StatureMethod | None = None
    assessments: list[AssessmentResponse] | None = None


class MeasurementResponse(MeasurementSnapshotBase):
    id: UUID
    subject_id: UUID
    responsible_id: UUID
    establishment_id: UUID
    created_at: datetime


class SubjectRefResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    dni: int
    sex: Sex
    name: str
    last_name: str
    birth_date: date


class EstablishmentRefResponse(IdentifierRefSchema):
    city: str
    province: str


class ResponsibleRefResponse(IdentifierRefSchema):
    last_name: str


class MeasurementListItem(MeasurementSnapshotBase):
    id: UUID
    subject: SubjectRefResponse
    establishment: EstablishmentRefResponse
    responsible: ResponsibleRefResponse


class EvolutionPoint(MeasurementSnapshotBase):
    id: UUID


class SubjectEvolutionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    subject: SubjectRefResponse
    points: list[EvolutionPoint]
