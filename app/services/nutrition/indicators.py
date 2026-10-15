from collections.abc import Callable, Iterable, Mapping
from typing import NamedTuple
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


class _Portion(NamedTuple):
    """A food found in the catalog and how many 100 g of it were eaten."""

    composition: FoodComposition
    hundreds_of_grams: float


class _Reading(NamedTuple):
    """A nutrient added up over the foods and how many had no value for it."""

    total: float
    foods_without: int


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
    portions, unknown_foods = _portions(items, compositions)
    catalog_readings = {
        code: _read_code(portions, code) for code in _catalog_codes(profile)
    }
    prioritized_readings = {n: _read_nutrient(portions, n) for n in PrioritizedNutrient}
    retinol_assumed = _retinol_assumed(portions)
    warnings = _warnings(
        catalog_readings, prioritized_readings, unknown_foods, retinol_assumed
    )
    energy = catalog_readings[ENERGY].total
    if energy <= 0:
        return NutritionIndicators(has_data=False, warnings=warnings)

    nutrients = _adequacies(prioritized_readings, energy, profile)
    # Capped ratios, so an excess of one nutrient does not hide a deficit (ADR-0020).
    mean_adequacy_ratio = sum(n.adequacy_capped for n in nutrients) / len(nutrients)
    energy_by_group = _energy_by_group(portions)
    return NutritionIndicators(
        has_data=True,
        energy_kcal=energy,
        nutrients=nutrients,
        mean_adequacy_ratio=mean_adequacy_ratio,
        macro_energy_share={
            macro: catalog_readings[code].total * kcal_per_gram / energy
            for macro, (code, kcal_per_gram) in MACRO_NUTRIENT_CODES.items()
        },
        gapa_energy_share={
            group: energy_by_group.get(group, 0.0) / energy for group in GapaGroup
        },
        limit_indicators=[
            LimitIndicator(
                code=limit.value,
                amount_per_1000_kcal=catalog_readings[limit.value].total
                / energy
                * 1000,
            )
            for limit in profile.limits
        ],
        warnings=warnings,
    )


def required_nutrient_codes(profile: ReferenceProfile = NINO_7_9) -> set[str]:
    """Return every catalog nutrient code the indicators read."""
    return (
        _catalog_codes(profile)
        | {VITAMIN_A_RAE, RETINOL}
        | set(_DIRECT_NUTRIENT_CODES.values())
    )


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


def _catalog_codes(profile: ReferenceProfile) -> set[str]:
    """Return the catalog codes added up as they are: energy, macros and limits."""
    codes = {ENERGY}
    codes.update(code for code, _ in MACRO_NUTRIENT_CODES.values())
    codes.update(limit.value for limit in profile.limits)
    return codes


def _portions(
    items: Iterable[FoodQuantity], compositions: Mapping[UUID, FoodComposition]
) -> tuple[list[_Portion], set[UUID]]:
    """Return the portions of the foods in the catalog and the ids of those not."""
    portions = []
    unknown_foods = set()
    for item in items:
        composition = compositions.get(item.food_id)
        if composition is None:
            unknown_foods.add(item.food_id)
        else:
            portions.append(_Portion(composition, item.grams / 100))
    return portions, unknown_foods


def _read(
    portions: list[_Portion],
    amount_per_100g: Callable[[Mapping[str, float]], float | None],
) -> _Reading:
    """Add up an amount over the portions, counting the foods that lack it."""
    total = 0.0
    foods_without = 0
    for composition, hundreds_of_grams in portions:
        amount = amount_per_100g(composition.per_100g)
        if amount is None:
            foods_without += 1
        else:
            total += hundreds_of_grams * amount
    return _Reading(total, foods_without)


def _read_code(portions: list[_Portion], code: str) -> _Reading:
    """Add up a catalog nutrient over the portions."""
    return _read(portions, lambda per_100g: per_100g.get(code))


def _read_nutrient(portions: list[_Portion], nutrient: PrioritizedNutrient) -> _Reading:
    """Add up a prioritized nutrient over the portions."""
    return _read(
        portions, lambda per_100g: prioritized_amount_per_100g(nutrient, per_100g)
    )


def _energy_by_group(portions: list[_Portion]) -> dict[GapaGroup, float]:
    """Add up the energy of the portions by GAPA group, leaving out foods with none."""
    energy_by_group: dict[GapaGroup, float] = {}
    for composition, hundreds_of_grams in portions:
        group = composition.gapa_group
        if group is not None:
            energy = hundreds_of_grams * composition.per_100g.get(ENERGY, 0.0)
            energy_by_group[group] = energy_by_group.get(group, 0.0) + energy
    return energy_by_group


def _retinol_assumed(portions: list[_Portion]) -> int:
    """Count the portions with vitamin A RAE but no retinol reading."""
    return sum(
        1
        for composition, _ in portions
        if VITAMIN_A_RAE in composition.per_100g and RETINOL not in composition.per_100g
    )


def _adequacies(
    prioritized_readings: Mapping[PrioritizedNutrient, _Reading],
    energy: float,
    profile: ReferenceProfile,
) -> list[NutrientAdequacy]:
    """Return how much of each prioritized nutrient the foods cover."""
    adequacies = []
    for nutrient in PrioritizedNutrient:
        per_1000_kcal = prioritized_readings[nutrient].total / energy * 1000
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


def _warnings(
    catalog_readings: Mapping[str, _Reading],
    prioritized_readings: Mapping[PrioritizedNutrient, _Reading],
    unknown_foods: set[UUID],
    retinol_assumed: int,
) -> list[str]:
    """Describe the data gaps found while adding up the foods."""
    missing = {
        code: reading.foods_without for code, reading in catalog_readings.items()
    }
    for nutrient, reading in prioritized_readings.items():
        missing[_nutrient_label(nutrient)] = reading.foods_without
    warnings = []
    if unknown_foods:
        warnings.append(
            f"{len(unknown_foods)} food(s) not found in the catalog and ignored"
        )
    for label, count in sorted(missing.items()):
        if count:
            warnings.append(f"{count} food(s) have no value for {label}, counted as 0")
    if retinol_assumed:
        warnings.append(
            f"{retinol_assumed} food(s) have vitamin A RAE but no retinol, "
            "retinol counted as 0"
        )
    return warnings


def _nutrient_label(nutrient: PrioritizedNutrient) -> str:
    """Return how a prioritized nutrient is named in a warning."""
    if nutrient == PrioritizedNutrient.VITAMIN_A:
        return "vitamin A (RAE)"
    return _DIRECT_NUTRIENT_CODES[nutrient]
