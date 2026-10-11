"""
Nutritional reference profiles used to judge a food combination.

Keys:   profile code (e.g. "nino_7_9")
Values: ReferenceProfile with the daily energy, the daily need of each
        prioritized nutrient, the energy share range of each macronutrient and
        the limits of fiber, sodium, saturated fat and added sugar.

Sources:
  Energy, micronutrients and macronutrient ranges: FAO/WHO references for the
  reference child, as given by US #169 (CA 1).
  Fiber and limits: PAHO nutrient profile / Law 27.642. Marked "to validate":
  the values were proposed and have not been confirmed with nutritionists yet.
"""

from dataclasses import dataclass
from typing import Literal

from app.domain.nutrition import Macronutrient, PrioritizedNutrient


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
class ReferenceProfile:
    """Everything a food combination is compared against for one kind of eater."""

    energy_kcal: float
    nutrients: dict[PrioritizedNutrient, NutrientReference]
    macro_ranges: dict[Macronutrient, MacroRange]
    limits: dict[str, LimitReference]

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
)

REFERENCE_PROFILES: dict[str, ReferenceProfile] = {"nino_7_9": NINO_7_9}
