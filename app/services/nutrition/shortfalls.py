"""Evaluate reference rules on final quantities, independently of the LP solver."""

from uuid import UUID

from app.domain.nutrition import (
    FoodComposition,
    FoodQuantity,
    NutritionIndicators,
    ReferenceProfile,
    UnmetConstraint,
    UnmetConstraintKind,
)

# Ignore sub-milligram / sub-millicalorie rounding noise. Macro shares are
# dimensionless, so their tolerance is expressed as a fraction instead.
ENERGY_TOLERANCE_KCAL = 1e-4
GROUP_TOLERANCE_GRAMS = 1e-4
MACRO_SHARE_TOLERANCE = 1e-6


def evaluate_shortfalls(
    quantities: list[FoodQuantity],
    compositions: dict[UUID, FoodComposition],
    indicators: NutritionIndicators,
    target: float,
    profile: ReferenceProfile,
) -> tuple[list[UnmetConstraint], list[str]]:
    """Evaluate energy, macro ranges and GAPA minima from the reference profile."""
    energy = indicators.energy_kcal or 0
    unmet = []
    if energy < target - ENERGY_TOLERANCE_KCAL:
        unmet.append(
            UnmetConstraint(
                UnmetConstraintKind.STOCK_INSUFFICIENT,
                "energy",
                target - energy,
                "kcal",
            )
        )
    for macro, allowed in profile.macro_ranges.items():
        share = indicators.macro_energy_share.get(macro, 0)
        if share < allowed.min_share - MACRO_SHARE_TOLERANCE:
            unmet.append(
                UnmetConstraint(
                    UnmetConstraintKind.MACRO_BELOW_MIN,
                    macro.value,
                    (allowed.min_share - share) * energy,
                    "kcal",
                )
            )
        if share > allowed.max_share + MACRO_SHARE_TOLERANCE:
            unmet.append(
                UnmetConstraint(
                    UnmetConstraintKind.MACRO_ABOVE_MAX,
                    macro.value,
                    (share - allowed.max_share) * energy,
                    "kcal",
                )
            )
    group_grams = {}
    for item in quantities:
        group = compositions[item.food_id].gapa_group
        if group:
            group_grams[group] = group_grams.get(group, 0) + item.grams
    for group in profile.gapa_portions:
        minimum = profile.gapa_minimum_per_1000_kcal(group) * energy / 1000
        missing = minimum - group_grams.get(group, 0)
        if missing > GROUP_TOLERANCE_GRAMS:
            unmet.append(
                UnmetConstraint(
                    UnmetConstraintKind.GAPA_GROUP_BELOW_MIN,
                    group.value,
                    missing,
                    "g",
                )
            )
    return unmet, sorted(group.value for group in group_grams)
