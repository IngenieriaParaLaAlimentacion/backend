import pytest

from app.domain.nutrition import Macronutrient, PrioritizedNutrient
from app.reference_data.nutrition_references import NINO_7_9

# Per 1,000 kcal, as listed in docs/plans/prog-lineal.md.
EXPECTED_PER_1000_KCAL = {
    PrioritizedNutrient.CALCIUM: 395.5,
    PrioritizedNutrient.VITAMIN_A: 282.5,
    PrioritizedNutrient.FOLATE: 169.5,
    PrioritizedNutrient.VITAMIN_B12: 1.02,
    PrioritizedNutrient.VITAMIN_C: 19.8,
    PrioritizedNutrient.IRON: 5.08,
    PrioritizedNutrient.ZINC: 3.16,
}


@pytest.mark.parametrize("nutrient,expected", EXPECTED_PER_1000_KCAL.items())
def test_nutrient_reference_per_1000_kcal(nutrient, expected):
    assert NINO_7_9.nutrient_per_1000_kcal(nutrient) == pytest.approx(
        expected, rel=0.01
    )


def test_profile_covers_every_prioritized_nutrient():
    assert set(NINO_7_9.nutrients) == set(PrioritizedNutrient)


def test_macro_ranges_can_add_up_to_the_whole_energy():
    ranges = NINO_7_9.macro_ranges.values()

    assert set(NINO_7_9.macro_ranges) == set(Macronutrient)
    assert sum(r.min_share for r in ranges) <= 1 <= sum(r.max_share for r in ranges)
