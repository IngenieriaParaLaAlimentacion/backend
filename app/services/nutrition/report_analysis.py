from collections.abc import Mapping
from uuid import UUID

from app.domain.nutrition import MonthlyIntakeAnalysis, ReferenceProfile
from app.schemas.nutrition.nutrition_report_schema import (
    NutritionReportAnalysis,
    ReportFoodSource,
    ReportFoodWithoutConversion,
    ReportGapaGroup,
    ReportLimit,
    ReportMacro,
    ReportNutrient,
    ReportNutrientSources,
)

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

    at_risk = set(analysis.nutrients_at_risk)
    out_of_range = {item.macro for item in analysis.macros_out_of_range}
    missing_groups = set(analysis.missing_gapa_groups)
    return NutritionReportAnalysis(
        energy_kcal=indicators.energy_kcal,
        mean_adequacy_percent=indicators.mean_adequacy_ratio * _PERCENT,
        nutrients=[
            ReportNutrient(
                nutrient=item.nutrient,
                amount_per_1000_kcal=item.amount_per_1000_kcal,
                adequacy_percent=item.adequacy_uncapped * _PERCENT,
                adequacy_capped_percent=item.adequacy_capped * _PERCENT,
                at_risk=item.nutrient in at_risk,
            )
            for item in indicators.nutrients
        ],
        macros=[
            ReportMacro(
                macro=macro,
                energy_share_percent=share * _PERCENT,
                min_percent=profile.macro_ranges[macro].min_share * _PERCENT,
                max_percent=profile.macro_ranges[macro].max_share * _PERCENT,
                in_range=macro not in out_of_range,
            )
            for macro, share in indicators.macro_energy_share.items()
        ],
        gapa_groups=[
            ReportGapaGroup(
                group=group,
                energy_share_percent=share * _PERCENT,
                missing=group in missing_groups,
            )
            for group, share in indicators.gapa_energy_share.items()
        ],
        limits=[
            ReportLimit(code=item.code, amount_per_1000_kcal=item.amount_per_1000_kcal)
            for item in indicators.limit_indicators
        ],
        top_sources=[
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
        ],
        foods_without_conversion=left_out,
        warnings=analysis.warnings,
    )
