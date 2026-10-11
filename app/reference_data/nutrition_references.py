"""
Nutritional reference profiles used to judge a food combination.

Keys:   profile code (e.g. "nino_7_9")
Values: ReferenceProfile with the daily energy, the daily need of each
        prioritized nutrient, the energy share range of each macronutrient and
        the limits of fiber, sodium, saturated fat and added sugar.

Sources (7 to 9 years):
  Micronutrients: FAO/WHO (2001), Human Vitamin and Mineral Requirements.
    https://www.fao.org/4/y2809e/y2809e00.htm
    Calcium Table 31 (700 mg); vitamin A Table 18 (500 µg RE); folate Table 13
    (300 µg DFE); vitamin B12 Table 14 (1.8 µg); vitamin C Table 15 (35 mg);
    iron Table 40 (8.9 mg at 10% bioavailability, rounded to 9); zinc Table 56
    (5.6 mg at moderate bioavailability).
  Energy: FAO/WHO/UNU (2004), Human Energy Requirements, Tables 4.2 and 4.3.
    https://www.fao.org/4/y5686e/y5686e06.htm
    1,770 is the mean of the six values for ages 7-8, 8-9 and 9-10, boys (1,692,
    1,830, 1,978 kcal) and girls (1,554, 1,698, 1,854 kcal): 1,768, rounded.
  Macronutrients: WHO/FAO (2003), TRS 916, Table 6.
    https://www.fao.org/4/ac911e/ac911e07.htm
    Protein 10-15% and fat 15-30% of the energy match. The table gives 55-75%
    for carbohydrates; the 40-65% used here is the criterion of a consulted
    nutritionist, not a published reference, to validate with the project's
    nutritionists.
  Sodium, saturated fat, added sugar: PAHO Nutrient Profile Model (2016).
    https://iris.paho.org/handle/10665.2/18622
    Sodium 1 mg per kcal, saturated fat 10% and free sugars 10% of the energy.
    The model flags products with an excess; it does not set intake limits. It
    speaks of free sugars while the catalog only has added sugar.
  GAPA portions: Ministerio de Salud de la Nación, Manual para la aplicación de las
    Guías Alimentarias para la Población Argentina.
    https://www.argentina.gob.ar/sites/default/files/bancos/2020-08/guias-alimentarias-para-la-poblacion-argentina_manual-de-aplicacion_0.pdf
    The manual gives the daily portions of groups 1 to 4 and the size of a portion
    in household measures, and in grams only for group 2 (60 g of bread or 125 g
    of cooked legumes, cereals or pasta) and for yogurt (200 g). The grams of the
    other portions are marked next to the constants.
  Fiber: 14 g per 1,000 kcal, suggested by a consulted nutritionist, to validate
    with the project's nutritionists. For comparison, the Institute of Medicine
    (2005) Dietary Reference Intakes report covers fiber; the figure was not
    checked on its page.
    https://www.nationalacademies.org/publications/10490
"""

from dataclasses import dataclass
from typing import Literal

from app.domain.nutrition import (
    GapaGroup,
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
    limits: dict[str, LimitReference]
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


# Limits are keyed by catalog nutrient code. Saturated fat and added sugar are
# 10% of the energy, converted to grams with 9 and 4 kcal per gram.
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
        # Protein and fat ranges already leave carbohydrates between 55% and 75%
        # of the energy, so only the 65% ceiling of carbohydrates can bind.
        Macronutrient.PROTEIN: MacroRange(0.10, 0.15),
        Macronutrient.LIPIDS: MacroRange(0.15, 0.30),
        Macronutrient.CARBOHYDRATES: MacroRange(0.40, 0.65),
    },
    limits={
        # To validate with nutritionists.
        "fibra_alimentaria": LimitReference("min", 14),
        "sodio": LimitReference("max", 1000),
        "saturados": LimitReference("max", 0.10 * 1000 / 9),
        "azucar_agregado": LimitReference("max", 0.10 * 1000 / 4),
    },
    # Daily portions are the manual's for the general population, not specific to
    # children of 7 to 9 years. Grams are of the food as the catalog weighs it, so
    # group 2 uses the 60 g of bread, not the 125 g of cooked cereal, which is
    # mostly water. Groups 1, 4 and 5 have no gram figure in the manual and are
    # provisional: 80 g for fruit or vegetables (WHO/FAO 2003 asks for 400 g a day,
    # in 5 portions), 100 g of meat (a portion is the palm of the hand) and 10 g of
    # oil (a tablespoon). Group 3 uses the 200 g of a glass of milk or a yogurt.
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
