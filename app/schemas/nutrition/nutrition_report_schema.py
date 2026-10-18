from datetime import date, datetime
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.nutrition import GapaGroup, Macronutrient, PrioritizedNutrient
from app.domain.nutrition_report import (
    SUMMARY_MAX_ITEMS,
    SUMMARY_TEXT_MAX_LENGTH,
    SummaryStatus,
)


class ReportNutrient(BaseModel):
    """How much of a prioritized nutrient the month's intakes cover."""

    nutrient: PrioritizedNutrient
    amount_per_1000_kcal: float = Field(
        description="Amount of the nutrient per 1,000 kcal, in its own unit.",
    )
    adequacy_percent: float = Field(
        description="Share of the reference covered, without a ceiling.",
    )
    adequacy_capped_percent: float = Field(
        description="Share of the reference covered, limited to 100.",
    )
    at_risk: bool = Field(
        description="Whether the intake is at risk of not covering the nutrient.",
    )


class ReportMacro(BaseModel):
    """Share of the energy a macronutrient provides and the range it should hold."""

    macro: Macronutrient
    energy_share_percent: float
    min_percent: float
    max_percent: float
    in_range: bool


class ReportGapaGroup(BaseModel):
    """Share of the energy that comes from one GAPA group."""

    group: GapaGroup
    energy_share_percent: float
    missing: bool = Field(
        description="Whether the group provided no energy at all in the month.",
    )


class ReportLimit(BaseModel):
    """Intake of fiber, sodium, saturated fat or added sugar, shown as information."""

    code: str = Field(description="Nutrient code in the food catalog.")
    amount_per_1000_kcal: float


class ReportFoodSource(BaseModel):
    """A catalog food and how much of a nutrient it gives per 100 kcal."""

    food_id: UUID
    name: str
    amount_per_100_kcal: float


class ReportNutrientSources(BaseModel):
    """The foods that best cover a nutrient the intake is short of."""

    nutrient: PrioritizedNutrient
    foods: list[ReportFoodSource]


class NutritionReportAnalysis(BaseModel):
    """The nutritional balance of a month, as calculated when the report was made.

    Shares and adequacies are percentages. It is stored with the report, so food
    names are kept in it and the catalog is not read again. ``energy_kcal`` and
    ``mean_adequacy_percent`` are null, and the lists empty, for a month with no
    intakes.
    """

    energy_kcal: float | None = None
    mean_adequacy_percent: float | None = Field(
        default=None,
        description="Mean of the capped adequacies of the prioritized nutrients.",
    )
    nutrients: list[ReportNutrient] = Field(default_factory=list)
    macros: list[ReportMacro] = Field(default_factory=list)
    gapa_groups: list[ReportGapaGroup] = Field(default_factory=list)
    limits: list[ReportLimit] = Field(default_factory=list)
    top_sources: list[ReportNutrientSources] = Field(default_factory=list)
    warnings: list[str] = Field(
        default_factory=list,
        description="Data gaps found while calculating, such as foods left out.",
    )


SummaryText = Annotated[str, Field(max_length=SUMMARY_TEXT_MAX_LENGTH)]


class NutritionReportSummary(BaseModel):
    """The summary of a report, written by the AI in Spanish, one text per section.

    A section with nothing to say is an empty string or an empty list. The AI
    returns this same shape.
    """

    overview: SummaryText = Field(
        description="How balanced the food received in the month was, overall.",
    )
    at_risk_nutrients: list[SummaryText] = Field(
        max_length=SUMMARY_MAX_ITEMS,
        description="One item per nutrient at risk, saying what that shortfall means.",
    )
    macros: SummaryText = Field(
        description="How the energy splits between proteins, lipids and carbohydrates.",
    )
    gapa_groups: SummaryText = Field(
        description="Which food groups weigh most in the energy and which are missing.",
    )
    incorporate: SummaryText = Field(
        description="A line on which foods to add for the nutrients at risk.",
    )
    limitations: list[SummaryText] = Field(
        max_length=SUMMARY_MAX_ITEMS,
        description="One item per data gap to keep in mind when reading the report.",
    )

    @field_validator("overview")
    @classmethod
    def _overview_not_blank(cls, value: str) -> str:
        """Reject an overview made only of whitespace."""
        if not value.strip():
            raise ValueError("overview must not be blank")
        return value

    @field_validator("at_risk_nutrients", "limitations")
    @classmethod
    def _items_not_blank(cls, value: list[str]) -> list[str]:
        """Reject a list item made only of whitespace."""
        if any(not item.strip() for item in value):
            raise ValueError("list items must not be blank")
        return value


class NutritionReportResponse(BaseModel):
    """A monthly nutrition report of an establishment."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    establishment_id: UUID
    month: str = Field(
        description="Calendar month of the report, formatted as `YYYY-MM`.",
        examples=["2026-09"],
    )
    has_data: bool = Field(
        description="False when the establishment received no food in the month.",
    )
    reference_profile: str = Field(
        description="Reference the intake was compared against, e.g. `nino_7_9`.",
    )
    analysis: NutritionReportAnalysis
    summary_status: SummaryStatus
    summary: NutritionReportSummary | None = Field(
        default=None,
        description="Summary written by the AI, as returned. Null unless generated.",
    )
    created_at: datetime
    updated_at: datetime

    @field_validator("month", mode="before")
    @classmethod
    def _format_month(cls, value: Any) -> Any:
        """Show the first day of the month the report is stored under as YYYY-MM."""
        return value.strftime("%Y-%m") if isinstance(value, date) else value
