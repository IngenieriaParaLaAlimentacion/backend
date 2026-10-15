from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from uuid import UUID

from app.domain.nutrition import (
    FoodComposition,
    FoodQuantity,
    GapaGroup,
    LimitIndicator,
    Macronutrient,
    NutrientAdequacy,
    NutritionIndicators,
    PrioritizedNutrient,
    ReferenceProfile,
)
from app.reference_data.nutrition_references import NINO_7_9

ENERGY = "valor_energetico"
VITAMIN_A_RAE = "vitamina_a_rae"
RETINOL = "retinol"
# Key of the derived vitamin A reading in retinol equivalents, never a catalog code.
VITAMIN_A_RE_KEY = "vitamina_a_re"

# Catalog nutrient code behind each prioritized nutrient. Vitamin A is absent:
# it is derived from RAE and retinol.
_DIRECT_NUTRIENT_CODES = {
    PrioritizedNutrient.CALCIUM: "calcio",
    PrioritizedNutrient.FOLATE: "folato_efd",
    PrioritizedNutrient.VITAMIN_B12: "vitamina_b12",
    PrioritizedNutrient.VITAMIN_C: "vitamina_c",
    PrioritizedNutrient.IRON: "hierro",
    PrioritizedNutrient.ZINC: "zinc",
}

# Catalog nutrient code and kcal per gram of each macronutrient.
MACRO_NUTRIENT_CODES = {
    Macronutrient.PROTEIN: ("proteinas", 4),
    Macronutrient.LIPIDS: ("lipidos_totales", 9),
    Macronutrient.CARBOHYDRATES: ("carbohidratos_disponibles", 4),
}


def required_nutrient_codes(profile: ReferenceProfile = NINO_7_9) -> set[str]:
    """Return every catalog nutrient code the indicators read."""
    codes = {ENERGY, VITAMIN_A_RAE, RETINOL, *_DIRECT_NUTRIENT_CODES.values()}
    codes.update(code for code, _ in MACRO_NUTRIENT_CODES.values())
    codes.update(limit.value for limit in profile.limits)
    return codes


def vitamin_a_re(per_100g: Mapping[str, float]) -> float | None:
    """Return a food's vitamin A in retinol equivalents per 100 g.

    RE = 2 x RAE - retinol, so a food missing retinol counts as zero retinol and
    one missing RAE has no vitamin A reading (None).
    """
    rae = per_100g.get(VITAMIN_A_RAE)
    if rae is None:
        return None
    return 2 * rae - per_100g.get(RETINOL, 0.0)


def prioritized_amount_per_100g(
    nutrient: PrioritizedNutrient, per_100g: Mapping[str, float]
) -> float | None:
    """Return a food's amount of a prioritized nutrient per 100 g, or None if the
    catalog has no reading. Vitamin A is in retinol equivalents.
    """
    if nutrient == PrioritizedNutrient.VITAMIN_A:
        return vitamin_a_re(per_100g)
    return per_100g.get(_DIRECT_NUTRIENT_CODES[nutrient])


@dataclass
class _Sums:
    """What adding up the foods leaves: totals and the gaps found on the way."""

    totals: dict[str, float] = field(default_factory=dict)
    energy_by_group: dict[GapaGroup, float] = field(default_factory=dict)
    missing: dict[str, int] = field(default_factory=dict)
    unknown_foods: set[UUID] = field(default_factory=set)
    retinol_assumed: int = 0


def _sum_foods(
    items: Iterable[FoodQuantity],
    compositions: Mapping[UUID, FoodComposition],
    profile: ReferenceProfile,
) -> _Sums:
    """Add up every nutrient of the foods and the energy of each GAPA group."""
    sums = _Sums()
    codes = required_nutrient_codes(profile) - {VITAMIN_A_RAE, RETINOL}
    for item in items:
        composition = compositions.get(item.food_id)
        if composition is None:
            sums.unknown_foods.add(item.food_id)
            continue
        factor = item.grams / 100
        per_100g = dict(composition.per_100g)
        re = vitamin_a_re(per_100g)
        if re is not None and RETINOL not in per_100g:
            sums.retinol_assumed += 1
        if re is not None:
            per_100g[VITAMIN_A_RE_KEY] = re
        for code in codes | {VITAMIN_A_RE_KEY}:
            amount = per_100g.get(code)
            if amount is None:
                sums.missing[code] = sums.missing.get(code, 0) + 1
                continue
            sums.totals[code] = sums.totals.get(code, 0.0) + factor * amount
        if composition.gapa_group is not None:
            sums.energy_by_group[composition.gapa_group] = sums.energy_by_group.get(
                composition.gapa_group, 0.0
            ) + factor * per_100g.get(ENERGY, 0.0)
    return sums


def _adequacies(
    totals: Mapping[str, float], energy: float, profile: ReferenceProfile
) -> list[NutrientAdequacy]:
    """Return how much of each prioritized nutrient the foods cover."""
    adequacies = []
    for nutrient in PrioritizedNutrient:
        code = _DIRECT_NUTRIENT_CODES.get(nutrient, VITAMIN_A_RE_KEY)
        per_1000_kcal = totals.get(code, 0.0) / energy * 1000
        adequacy = per_1000_kcal / profile.nutrient_per_1000_kcal(nutrient)
        adequacies.append(
            NutrientAdequacy(
                nutrient=nutrient,
                amount_per_1000_kcal=per_1000_kcal,
                adequacy_uncapped=adequacy,
                adequacy_capped=min(1.0, adequacy),
            )
        )
    return adequacies


def calculate_indicators(
    items: Iterable[FoodQuantity],
    compositions: Mapping[UUID, FoodComposition],
    profile: ReferenceProfile = NINO_7_9,
) -> NutritionIndicators:
    """Return the balance indicators of foods in grams.

    ``compositions`` holds the foods in ``items``. A nutrient a food has no
    reading for counts as zero and is reported once in ``warnings``. When the
    foods carry no energy the result has ``has_data`` false and nothing else.
    """
    sums = _sum_foods(items, compositions, profile)
    totals = sums.totals
    warnings = _warnings(sums.missing, sums.unknown_foods, sums.retinol_assumed)
    energy = totals.get(ENERGY, 0.0)
    if energy <= 0:
        return NutritionIndicators(has_data=False, warnings=warnings)

    nutrients = _adequacies(totals, energy, profile)
    # The mean adequacy ratio (MAR) averages each nutrient's adequacy ratio, capped at 1
    # so that a nutrient in excess does not mask one in deficit (INDDEX Data4Diets):
    # https://www.anh-academy.org/data4diets/indicator/mean-adequacy-ratio-mar
    return NutritionIndicators(
        has_data=True,
        energy_kcal=energy,
        nutrients=nutrients,
        mean_adequacy_ratio=sum(n.adequacy_capped for n in nutrients) / len(nutrients),
        macro_energy_share={
            macro: totals.get(code, 0.0) * kcal_per_gram / energy
            for macro, (code, kcal_per_gram) in MACRO_NUTRIENT_CODES.items()
        },
        gapa_energy_share={
            group: sums.energy_by_group.get(group, 0.0) / energy for group in GapaGroup
        },
        limit_indicators=[
            LimitIndicator(
                code=limit.value,
                amount_per_1000_kcal=totals.get(limit.value, 0.0) / energy * 1000,
            )
            for limit in profile.limits
        ],
        warnings=warnings,
    )


def _warnings(
    missing: Mapping[str, int], unknown_foods: set[UUID], retinol_assumed: int
) -> list[str]:
    """Describe the data gaps found while adding up the foods."""
    warnings = []
    if unknown_foods:
        warnings.append(
            f"{len(unknown_foods)} food(s) not found in the catalog and ignored"
        )
    for code, count in sorted(missing.items()):
        label = "vitamin A (RAE)" if code == VITAMIN_A_RE_KEY else code
        warnings.append(f"{count} food(s) have no value for {label}, counted as 0")
    if retinol_assumed:
        warnings.append(
            f"{retinol_assumed} food(s) have vitamin A RAE but no retinol, "
            "retinol counted as 0"
        )
    return warnings
