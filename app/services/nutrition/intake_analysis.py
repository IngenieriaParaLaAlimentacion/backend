from collections.abc import Iterable, Mapping
from uuid import UUID

from app.domain.food_catalog import FoodNutrientRow
from app.domain.nutrition import (
    FoodComposition,
    FoodQuantity,
    FoodSource,
    GapaGroup,
    MacroOutOfRange,
    MonthlyIntakeAnalysis,
    PrioritizedNutrient,
)
from app.reference_data.nutrition_references import NINO_7_9, ReferenceProfile
from app.services.nutrition.indicators import (
    ENERGY,
    calculate_indicators,
    prioritized_amount_per_100g,
)

# A nutrient covering less than this share of its reference is at risk.
RISK_ADEQUACY_THRESHOLD = 2 / 3
TOP_SOURCES_COUNT = 5


def compositions_from_rows(
    rows: Iterable[FoodNutrientRow],
) -> dict[UUID, FoodComposition]:
    """Group (food, nutrient) rows into one composition per food."""
    compositions: dict[UUID, FoodComposition] = {}
    for row in rows:
        composition = compositions.get(row.food_id)
        if composition is None:
            group = (
                GapaGroup(row.gapa_category_code) if row.gapa_category_code else None
            )
            composition = FoodComposition(row.food_id, group, {})
            compositions[row.food_id] = composition
        composition.per_100g[row.nutrient_code] = float(row.amount_per_100g)
    return compositions


def analyze_intake(
    items: Iterable[FoodQuantity],
    compositions: Mapping[UUID, FoodComposition],
    catalog: Mapping[UUID, FoodComposition],
    profile: ReferenceProfile = NINO_7_9,
) -> MonthlyIntakeAnalysis:
    """Judge what an establishment received, in grams, against the profile.

    ``compositions`` holds the foods in ``items`` and ``catalog`` every food that
    could be suggested to cover a shortfall. With no energy there is nothing to
    judge, so no shortfall is reported.
    """
    indicators = calculate_indicators(items, compositions, profile)
    if not indicators.has_data:
        return MonthlyIntakeAnalysis(has_data=False, warnings=indicators.warnings)

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
        top_sources={n: top_sources(n, catalog) for n in at_risk},
        warnings=indicators.warnings,
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
            or not amount
            or amount < 0
            or composition.gapa_group in (None, GapaGroup.OPTIONAL)
        ):
            continue
        sources.append(FoodSource(food_id, amount / energy * 100))
    sources.sort(key=lambda s: s.amount_per_100_kcal, reverse=True)
    return sources[:count]
