"""
Nutritional reference profiles used to judge a food combination, keyed by profile
code (e.g. "nino_7_9").

Sources (7 to 9 years):
  FAO/WHO (2001), Human Vitamin and Mineral Requirements, Tables 13, 14, 15, 18,
    31, 40 and 56. https://www.fao.org/4/y2809e/y2809e00.htm
  FAO/WHO/UNU (2004), Human Energy Requirements, Tables 4.2 and 4.3.
    https://www.fao.org/4/y5686e/y5686e06.htm
  WHO/FAO (2003), Diet, Nutrition and the Prevention of Chronic Diseases, TRS 916,
    Table 6. https://www.fao.org/4/ac911e/ac911e07.htm
  Ministerio de Salud de la Nación, Manual para la aplicación de las Guías
    Alimentarias para la Población Argentina.
    https://www.argentina.gob.ar/sites/default/files/bancos/2020-08/guias-alimentarias-para-la-poblacion-argentina_manual-de-aplicacion_0.pdf

How each value was chosen: docs/adr/0020-nutrition-base-data.md
"""

from dataclasses import dataclass
from typing import Literal

from app.domain.nutrition import (
    GapaGroup,
    LimitedNutrient,
    Macronutrient,
    MealType,
    PrioritizedNutrient,
)


@dataclass(frozen=True)
class NutrientReference:
    """Daily need of a nutrient, in ``unit``."""

    amount_per_day: float
    unit: str
    bioavailability_note: str | None = None


@dataclass(frozen=True)
class MacroRange:
    """Range of the energy share a macronutrient should provide (0 to 1)."""

    min_share: float
    max_share: float


@dataclass(frozen=True)
class LimitReference:
    """Bound on a nutrient, per 1,000 kcal, in the nutrient's catalog unit.

    ``kind`` says whether ``amount_per_1000_kcal`` is a floor or a ceiling.
    """

    kind: Literal["min", "max"]
    amount_per_1000_kcal: float


@dataclass(frozen=True)
class GapaPortion:
    """Daily portions of a GAPA group and the grams one portion weighs."""

    daily_portions: float
    grams_per_portion: float


@dataclass(frozen=True)
class ReferenceProfile:
    """Everything a food combination is compared against for one kind of eater."""

    energy_kcal: float
    nutrients: dict[PrioritizedNutrient, NutrientReference]
    macro_ranges: dict[Macronutrient, MacroRange]
    limits: dict[LimitedNutrient, LimitReference]
    gapa_portions: dict[GapaGroup, GapaPortion]
    meal_energy_fractions: dict[MealType, float]

    def gapa_minimum_per_1000_kcal(self, group: GapaGroup) -> float:
        """Return the grams of a GAPA group that 1,000 kcal of food should hold."""
        portion = self.gapa_portions[group]
        return (
            portion.daily_portions * portion.grams_per_portion / self.energy_kcal * 1000
        )

    def nutrient_per_1000_kcal(self, nutrient: PrioritizedNutrient) -> float:
        """Return how much of the nutrient 1,000 kcal of food should provide."""
        return self.nutrients[nutrient].amount_per_day / self.energy_kcal * 1000


NINO_7_9 = ReferenceProfile(
    energy_kcal=1770,
    nutrients={
        PrioritizedNutrient.CALCIUM: NutrientReference(700, "mg"),
        PrioritizedNutrient.VITAMIN_A: NutrientReference(500, "µg RE"),
        PrioritizedNutrient.FOLATE: NutrientReference(300, "µg DFE"),
        PrioritizedNutrient.VITAMIN_B12: NutrientReference(1.8, "µg"),
        PrioritizedNutrient.VITAMIN_C: NutrientReference(35, "mg"),
        PrioritizedNutrient.IRON: NutrientReference(
            9, "mg", bioavailability_note="10% bioavailability"
        ),
        PrioritizedNutrient.ZINC: NutrientReference(
            5.6, "mg", bioavailability_note="moderate bioavailability"
        ),
    },
    macro_ranges={
        Macronutrient.PROTEIN: MacroRange(0.10, 0.15),
        Macronutrient.LIPIDS: MacroRange(0.15, 0.30),
        Macronutrient.CARBOHYDRATES: MacroRange(0.55, 0.75),
    },
    limits={
        # The fiber floor is a nutritionist's criterion, not published, to validate
        # with the project's nutritionists. The rest are TRS 916 Table 6.
        LimitedNutrient.FIBER: LimitReference("min", 14),
        LimitedNutrient.SODIUM: LimitReference("max", 2000 / 1770 * 1000),  # 2 g a day
        LimitedNutrient.SATURATED_FAT: LimitReference("max", 0.10 * 1000 / 9),
        LimitedNutrient.ADDED_SUGAR: LimitReference("max", 0.10 * 1000 / 4),
    },
    # Portions are the manual's, for the general population. Only group 2 (60 g) and
    # dairy (200 g) have grams in the manual; groups 1, 4 and 5 are provisional.
    gapa_portions={
        GapaGroup.FRUITS_AND_VEGETABLES: GapaPortion(5, 80),
        GapaGroup.LEGUMES_CEREALS_BREAD_PASTA: GapaPortion(4, 60),
        GapaGroup.DAIRY: GapaPortion(3, 200),
        GapaGroup.MEAT_AND_EGGS: GapaPortion(1, 100),
        GapaGroup.OILS_NUTS_AND_SEEDS: GapaPortion(2, 10),
    },
    # Provisional: no official Argentine source found for the share of the daily
    # energy each meal covers. Within the ranges of generic school meal guides.
    meal_energy_fractions={
        MealType.BREAKFAST: 0.20,
        MealType.LUNCH: 0.35,
        MealType.SNACK: 0.15,
        MealType.DINNER: 0.30,
    },
)

REFERENCE_PROFILES: dict[str, ReferenceProfile] = {"nino_7_9": NINO_7_9}
