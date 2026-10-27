from datetime import date, datetime
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator

from app.domain.nutrition import GapaGroup, Macronutrient, PrioritizedNutrient
from app.domain.nutrition_report import (
    SCOPE_NOTE,
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
    reference_per_1000_kcal: float | None = Field(
        default=None,
        description="Amount 1,000 kcal of food should provide, in the nutrient's own "
        "unit. Null in reports saved before it was stored.",
    )
    minimum_per_1000_kcal: float | None = Field(
        default=None,
        description="Amount per 1,000 kcal below which the nutrient is at risk. "
        "Null in reports saved before it was stored.",
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


class ReportFoodWithoutConversion(BaseModel):
    """A food received in the month that was left out for lacking a gram conversion."""

    food_id: UUID
    name: str


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
    foods_without_conversion: list[ReportFoodWithoutConversion] = Field(
        default_factory=list,
        description="Foods received in the month and left out of the calculation "
        "because they have no known conversion to grams.",
    )
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
        description="The story of the month: how balanced the food was and which "
        "pattern stands out.",
    )
    at_risk_nutrients: list[SummaryText] = Field(
        max_length=SUMMARY_MAX_ITEMS,
        description="One item per nutrient at risk, saying what falling short of it "
        "means and why it matters.",
    )
    macros: SummaryText = Field(
        description="What the split of the energy between proteins, lipids and "
        "carbohydrates suggests.",
    )
    gapa_groups: SummaryText = Field(
        description="What the weight of each food group says, and why a missing group "
        "matters.",
    )
    incorporate: SummaryText = Field(
        description="A line on which foods to add for the nutrients at risk.",
    )
    conclusion: SummaryText = Field(
        default="",
        description="What deserves attention first and why, closing the report.",
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


def _format_month(value: Any) -> Any:
    """Show the first day of the month a report is stored under as YYYY-MM."""
    return value.strftime("%Y-%m") if isinstance(value, date) else value


ReportMonth = Annotated[
    str,
    BeforeValidator(_format_month),
    Field(
        description="Calendar month of the report, formatted as `YYYY-MM`.",
        examples=["2026-09"],
    ),
]

ReportHasData = Annotated[
    bool,
    Field(
        description="False when there is no energy to judge in the month: no food "
        "was received, or only food without energy.",
    ),
]


class NutritionReportListItem(BaseModel):
    """The basics of a saved monthly report, as listed for an establishment."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    month: ReportMonth
    has_data: ReportHasData
    summary_status: SummaryStatus
    created_at: datetime


class NutritionReportResponse(BaseModel):
    """A monthly nutrition report of an establishment."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    establishment_id: UUID
    month: ReportMonth
    has_data: ReportHasData
    reference_profile: str = Field(
        description="Reference the intake was compared against, e.g. `nino_7_9`.",
    )
    analysis: NutritionReportAnalysis
    summary_status: SummaryStatus
    summary: NutritionReportSummary | None = Field(
        default=None,
        description="Summary written by the AI, as returned. Null unless generated.",
    )
    scope_note: str = Field(
        default=SCOPE_NOTE,
        description="Fixed note on what the report assesses and what it does not.",
    )
    created_at: datetime
    updated_at: datetime
