from collections.abc import Iterable, Mapping
from uuid import UUID

from app.domain.nutrition import (
    FoodComposition,
    FoodQuantity,
    FoodSource,
    GapaGroup,
    MacroOutOfRange,
    MonthlyIntakeAnalysis,
    PrioritizedNutrient,
    ReferenceProfile,
)
from app.reference_data.nutrition_references import NINO_7_9
from app.services.nutrition.indicators import (
    ENERGY,
    calculate_indicators,
    prioritized_amount_per_100g,
)

# A nutrient whose uncapped adequacy ratio (intake / reference, the NAR of INDDEX
# Data4Diets) falls below this is at risk of inadequacy. Two thirds of the
# reference is a traditional fixed cutoff for inadequate intake in food
# consumption surveys, next to one half and three fourths (National Research
# Council, 1986, Nutrient Adequacy: Assessment Using Food Consumption Surveys):
# https://www.nationalacademies.org/read/618/chapter/2
# It flags a risk, it does not estimate how many people are inadequate.
RISK_ADEQUACY_THRESHOLD = 2 / 3

# How many foods are suggested for each nutrient at risk.
TOP_SOURCES_COUNT = 5


def analyze_intake(
    items: Iterable[FoodQuantity],
    compositions: Mapping[UUID, FoodComposition],
    profile: ReferenceProfile = NINO_7_9,
) -> MonthlyIntakeAnalysis:
    """Judge what an establishment received, in grams, against the profile.

    ``compositions`` holds the foods in ``items``. ``top_sources`` is left empty:
    the caller fills it with ``top_sources`` once it has loaded the catalog.
    """
    indicators = calculate_indicators(items, compositions, profile)
    # With no energy there is nothing to judge, so no shortfall is reported.
    if not indicators.has_data:
        return MonthlyIntakeAnalysis(has_data=False, warnings=list(indicators.warnings))

    at_risk = [
        n.nutrient
        for n in indicators.nutrients
        if n.adequacy_uncapped < RISK_ADEQUACY_THRESHOLD
    ]
    macros_out_of_range = []
    for macro, share in indicators.macro_energy_share.items():
        allowed = profile.macro_ranges[macro]
        if not allowed.min_share <= share <= allowed.max_share:
            macros_out_of_range.append(
                MacroOutOfRange(macro, share, allowed.min_share, allowed.max_share)
            )
    # Optional foods are not a group to cover, so their absence is no shortfall.
    missing_groups = [
        group
        for group, share in indicators.gapa_energy_share.items()
        if share == 0 and group != GapaGroup.OPTIONAL
    ]
    return MonthlyIntakeAnalysis(
        has_data=True,
        indicators=indicators,
        nutrients_at_risk=at_risk,
        macros_out_of_range=macros_out_of_range,
        missing_gapa_groups=missing_groups,
        warnings=list(indicators.warnings),
    )


def top_sources(
    nutrient: PrioritizedNutrient,
    catalog: Mapping[UUID, FoodComposition],
    count: int = TOP_SOURCES_COUNT,
) -> list[FoodSource]:
    """Return the foods giving the most of a nutrient per 100 kcal, best first.

    Foods without energy, without the nutrient, outside every GAPA group or in
    the optional group are left out.
    """
    sources = []
    for food_id, composition in catalog.items():
        energy = composition.per_100g.get(ENERGY, 0.0)
        amount = prioritized_amount_per_100g(nutrient, composition.per_100g)
        if (
            energy <= 0
            or amount is None
            or amount <= 0
            or composition.gapa_group in (None, GapaGroup.OPTIONAL)
        ):
            continue
        sources.append(
            FoodSource(food_id=food_id, amount_per_100_kcal=(amount / energy * 100))
        )
    sources.sort(key=lambda s: s.amount_per_100_kcal, reverse=True)
    return sources[:count]
