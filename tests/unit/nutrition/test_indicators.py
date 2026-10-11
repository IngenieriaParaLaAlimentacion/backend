import uuid

import pytest

from app.domain.nutrition import (
    FoodComposition,
    FoodQuantity,
    GapaGroup,
    Macronutrient,
    PrioritizedNutrient,
)
from app.reference_data.nutrition_references import NINO_7_9
from app.services.nutrition.indicators import calculate_indicators
from tests.unit.nutrition.helpers import composition


def indicators_of(*foods_and_grams: tuple[FoodComposition, float]):
    items = [FoodQuantity(f.food_id, grams) for f, grams in foods_and_grams]
    compositions = {f.food_id: f for f, _ in foods_and_grams}
    return calculate_indicators(items, compositions)


def adequacy_of(result, nutrient: PrioritizedNutrient):
    return next(n for n in result.nutrients if n.nutrient == nutrient)


def test_energy_and_macro_shares_come_from_the_grams_eaten():
    # 100 g give 100 kcal: 5 g protein (20 kcal), 3 g fat (27), 13.25 g carbs (53).
    base = composition(
        {
            "valor_energetico": 100,
            "proteinas": 5,
            "lipidos_totales": 3,
            "carbohidratos_disponibles": 13.25,
        }
    )

    result = indicators_of((base, 200))

    assert result.has_data
    assert result.energy_kcal == pytest.approx(200)
    assert result.macro_energy_share == pytest.approx(
        {
            Macronutrient.PROTEIN: 0.20,
            Macronutrient.LIPIDS: 0.27,
            Macronutrient.CARBOHYDRATES: 0.53,
        }
    )


def test_adequacy_is_amount_per_1000_kcal_over_the_reference():
    # 200 g give 200 kcal and 400 mg of calcium: 2,000 mg per 1,000 kcal.
    milk = composition({"valor_energetico": 100, "calcio": 200})

    calcium = adequacy_of(indicators_of((milk, 200)), PrioritizedNutrient.CALCIUM)

    assert calcium.amount_per_1000_kcal == pytest.approx(2000)
    expected = 2000 / (700 / 1770 * 1000)
    assert calcium.adequacy_uncapped == pytest.approx(expected)


def test_excess_of_one_nutrient_does_not_make_up_for_a_deficit_of_another():
    milk = composition({"valor_energetico": 100, "calcio": 200})

    result = indicators_of((milk, 100))

    assert adequacy_of(result, PrioritizedNutrient.CALCIUM).adequacy_uncapped > 1
    assert adequacy_of(result, PrioritizedNutrient.CALCIUM).adequacy_capped == 1
    # Calcium is the only nutrient covered, so it is 1 of the 7 equal parts.
    assert result.mean_adequacy_ratio == pytest.approx(1 / 7)


def test_vitamin_a_counts_in_retinol_equivalents():
    # RE = 2 x RAE - retinol = 160 per 100 g; 200 g give 320 RE over 200 kcal.
    liver = composition({"valor_energetico": 100, "vitamina_a_rae": 100, "retinol": 40})

    result = indicators_of((liver, 200))

    vitamin_a = adequacy_of(result, PrioritizedNutrient.VITAMIN_A)
    assert vitamin_a.amount_per_1000_kcal == pytest.approx(1600)
    assert not any("retinol" in warning for warning in result.warnings)


def test_missing_retinol_counts_as_zero_and_is_reported():
    carrot = composition({"valor_energetico": 100, "vitamina_a_rae": 100})

    result = indicators_of((carrot, 100))

    vitamin_a = adequacy_of(result, PrioritizedNutrient.VITAMIN_A)
    assert vitamin_a.amount_per_1000_kcal == pytest.approx(2000)
    assert any("retinol" in warning for warning in result.warnings)


def test_nutrient_without_reading_counts_as_zero_and_is_reported():
    rice = composition({"valor_energetico": 130})

    result = indicators_of((rice, 100))

    assert adequacy_of(result, PrioritizedNutrient.ZINC).adequacy_uncapped == 0
    assert any("zinc" in warning for warning in result.warnings)


def test_energy_share_by_group_ignores_foods_without_group():
    veg = composition({"valor_energetico": 50}, GapaGroup.FRUITS_AND_VEGETABLES)
    meat = composition({"valor_energetico": 150}, GapaGroup.MEAT_AND_EGGS)
    salt = composition({"valor_energetico": 0})
    plain = composition({"valor_energetico": 100})

    result = indicators_of((veg, 100), (meat, 100), (salt, 100), (plain, 100))

    shares = result.gapa_energy_share
    assert shares[GapaGroup.FRUITS_AND_VEGETABLES] == pytest.approx(50 / 300)
    assert shares[GapaGroup.MEAT_AND_EGGS] == pytest.approx(150 / 300)
    # A group with nothing is listed as zero so a missing group is visible.
    assert shares[GapaGroup.DAIRY] == 0
    assert set(shares) == set(GapaGroup)


def test_limit_indicators_are_reported_per_1000_kcal():
    snack = composition({"valor_energetico": 500, "sodio": 800, "fibra_alimentaria": 2})

    result = indicators_of((snack, 100))

    by_code = {i.code: i.amount_per_1000_kcal for i in result.limit_indicators}
    assert set(by_code) == set(NINO_7_9.limits)
    assert by_code["sodio"] == pytest.approx(1600)
    assert by_code["fibra_alimentaria"] == pytest.approx(4)


@pytest.mark.parametrize(
    "build",
    [
        pytest.param(lambda: [], id="empty-list"),
        pytest.param(
            lambda: [(composition({"valor_energetico": 0}), 100)], id="no-energy"
        ),
        pytest.param(lambda: [(composition({}), 100)], id="no-readings"),
    ],
)
def test_foods_without_energy_give_no_data_instead_of_dividing_by_zero(build):
    result = indicators_of(*build())

    assert not result.has_data
    assert result.mean_adequacy_ratio is None
    assert result.nutrients == []


def test_food_missing_from_the_catalog_is_ignored_and_reported():
    rice = composition({"valor_energetico": 100})
    items = [FoodQuantity(rice.food_id, 100), FoodQuantity(uuid.uuid4(), 100)]

    result = calculate_indicators(items, {rice.food_id: rice})

    assert result.energy_kcal == pytest.approx(100)
    assert any("not found" in warning for warning in result.warnings)
