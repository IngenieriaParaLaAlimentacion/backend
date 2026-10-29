from collections.abc import Mapping
from uuid import UUID

from app.domain.nutrition import (
    MonthlyIntakeAnalysis,
    NutritionIndicators,
    ReferenceProfile,
)
from app.schemas.nutrition_reports.nutrition_report_schema import (
    NutritionReportAnalysis,
    ReportFoodSource,
    ReportFoodWithoutConversion,
    ReportGapaGroup,
    ReportLimit,
    ReportMacro,
    ReportNutrient,
    ReportNutrientSources,
)
from app.services.nutrition.intake_analysis import RISK_ADEQUACY_THRESHOLD

_PERCENT = 100


def build_analysis(
    analysis: MonthlyIntakeAnalysis,
    profile: ReferenceProfile,
    food_names: Mapping[UUID, str],
) -> NutritionReportAnalysis:
    """Return the report snapshot of a monthly analysis, with shares as percentages.

    ``food_names`` names every food in ``analysis.top_sources`` and every food left
    out for lacking a conversion. A month with no data gives a snapshot holding
    only the foods left out and the warnings.
    """
    left_out = [
        ReportFoodWithoutConversion(food_id=food_id, name=food_names[food_id])
        for food_id in analysis.foods_without_conversion
    ]
    indicators = analysis.indicators
    if indicators is None:
        return NutritionReportAnalysis(
            foods_without_conversion=left_out, warnings=analysis.warnings
        )

    return NutritionReportAnalysis(
        energy_kcal=indicators.energy_kcal,
        mean_adequacy_percent=indicators.mean_adequacy_ratio * _PERCENT,
        nutrients=_nutrients(analysis, indicators, profile),
        macros=_macros(analysis, indicators, profile),
        gapa_groups=_gapa_groups(analysis, indicators),
        limits=_limits(indicators),
        top_sources=_top_sources(analysis, food_names),
        foods_without_conversion=left_out,
        warnings=analysis.warnings,
    )


def _nutrients(
    analysis: MonthlyIntakeAnalysis,
    indicators: NutritionIndicators,
    profile: ReferenceProfile,
) -> list[ReportNutrient]:
    """Return each prioritized nutrient with its reference, minimum and adequacy."""
    at_risk = set(analysis.nutrients_at_risk)
    reference = {
        item.nutrient: profile.nutrient_per_1000_kcal(item.nutrient)
        for item in indicators.nutrients
    }
    return [
        ReportNutrient(
            nutrient=item.nutrient,
            amount_per_1000_kcal=item.amount_per_1000_kcal,
            reference_per_1000_kcal=reference[item.nutrient],
            minimum_per_1000_kcal=reference[item.nutrient] * RISK_ADEQUACY_THRESHOLD,
            adequacy_percent=item.adequacy_uncapped * _PERCENT,
            adequacy_capped_percent=item.adequacy_capped * _PERCENT,
            at_risk=item.nutrient in at_risk,
        )
        for item in indicators.nutrients
    ]


def _macros(
    analysis: MonthlyIntakeAnalysis,
    indicators: NutritionIndicators,
    profile: ReferenceProfile,
) -> list[ReportMacro]:
    """Return the energy share of each macronutrient with the range it should hold."""
    out_of_range = {item.macro for item in analysis.macros_out_of_range}
    return [
        ReportMacro(
            macro=macro,
            energy_share_percent=share * _PERCENT,
            min_percent=profile.macro_ranges[macro].min_share * _PERCENT,
            max_percent=profile.macro_ranges[macro].max_share * _PERCENT,
            in_range=macro not in out_of_range,
        )
        for macro, share in indicators.macro_energy_share.items()
    ]


def _gapa_groups(
    analysis: MonthlyIntakeAnalysis, indicators: NutritionIndicators
) -> list[ReportGapaGroup]:
    """Return the energy share of each GAPA group, flagging the missing ones."""
    missing_groups = set(analysis.missing_gapa_groups)
    return [
        ReportGapaGroup(
            group=group,
            energy_share_percent=share * _PERCENT,
            missing=group in missing_groups,
        )
        for group, share in indicators.gapa_energy_share.items()
    ]


def _limits(indicators: NutritionIndicators) -> list[ReportLimit]:
    """Return the intake of each limited nutrient per 1,000 kcal."""
    return [
        ReportLimit(code=item.code, amount_per_1000_kcal=item.amount_per_1000_kcal)
        for item in indicators.limit_indicators
    ]


def _top_sources(
    analysis: MonthlyIntakeAnalysis, food_names: Mapping[UUID, str]
) -> list[ReportNutrientSources]:
    """Return the named foods suggested for each nutrient at risk."""
    return [
        ReportNutrientSources(
            nutrient=nutrient,
            foods=[
                ReportFoodSource(
                    food_id=source.food_id,
                    name=food_names[source.food_id],
                    amount_per_100_kcal=source.amount_per_100_kcal,
                )
                for source in sources
            ],
        )
        for nutrient, sources in analysis.top_sources.items()
    ]
