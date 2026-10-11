import uuid

import pytest

from app.domain.nutrition import (
    FoodComposition,
    FoodQuantity,
    GapaGroup,
    Macronutrient,
    PrioritizedNutrient,
)
from app.services.nutrition.intake_analysis import analyze_intake, top_sources

CALCIUM = PrioritizedNutrient.CALCIUM


def food(per_100g: dict[str, float], group: GapaGroup | None = GapaGroup.DAIRY):
    return FoodComposition(food_id=uuid.uuid4(), gapa_group=group, per_100g=per_100g)


def analyze(received, catalog=()):
    items = [FoodQuantity(f.food_id, grams) for f, grams in received]
    compositions = {f.food_id: f for f, _ in received}
    return analyze_intake(items, compositions, {f.food_id: f for f in catalog})


# The calcium reference is 395 mg per 1,000 kcal, so two thirds of it is 264.
@pytest.mark.parametrize(
    ("calcium_per_100_kcal", "at_risk"),
    [(20, True), (30, False)],
)
def test_nutrient_below_two_thirds_of_its_reference_is_at_risk(
    calcium_per_100_kcal, at_risk
):
    bread = food({"valor_energetico": 100, "calcio": calcium_per_100_kcal})

    result = analyze([(bread, 500)])

    assert (CALCIUM in result.nutrients_at_risk) is at_risk


def test_no_intake_gives_no_data_instead_of_flagging_every_deficit():
    result = analyze([])

    assert not result.has_data
    assert result.nutrients_at_risk == []
    assert result.missing_gapa_groups == []


def test_macro_outside_its_range_is_reported():
    # 100 kcal that are 100% carbohydrates: above the 65% ceiling, and with no
    # protein or fat, below their floors.
    rice = food({"valor_energetico": 100, "carbohidratos_disponibles": 25})

    result = analyze([(rice, 100)])

    out = {m.macro: m.energy_share for m in result.macros_out_of_range}
    assert out == pytest.approx(
        {
            Macronutrient.CARBOHYDRATES: 1.0,
            Macronutrient.PROTEIN: 0.0,
            Macronutrient.LIPIDS: 0.0,
        }
    )


def test_absent_groups_are_reported_except_the_optional_one():
    veg = food({"valor_energetico": 50}, GapaGroup.FRUITS_AND_VEGETABLES)

    result = analyze([(veg, 100)])

    assert GapaGroup.OPTIONAL not in result.missing_gapa_groups
    assert set(result.missing_gapa_groups) == set(GapaGroup) - {
        GapaGroup.FRUITS_AND_VEGETABLES,
        GapaGroup.OPTIONAL,
    }


def test_sources_are_ranked_by_amount_per_100_kcal_and_limited_to_the_count():
    catalog = [food({"valor_energetico": 100, "calcio": c}) for c in range(10, 100, 10)]

    ranked = top_sources(CALCIUM, catalog_by_id(catalog), count=3)

    assert [round(s.amount_per_100_kcal) for s in ranked] == [90, 80, 70]


def test_sources_skip_optional_ungrouped_and_energyless_foods():
    good = food({"valor_energetico": 100, "calcio": 10})
    candidates = [
        good,
        food({"valor_energetico": 100, "calcio": 500}, GapaGroup.OPTIONAL),
        food({"valor_energetico": 100, "calcio": 500}, None),
        food({"valor_energetico": 0, "calcio": 500}),
        food({"valor_energetico": 100}),
    ]

    ranked = top_sources(CALCIUM, catalog_by_id(candidates))

    assert [s.food_id for s in ranked] == [good.food_id]


def test_sources_are_computed_for_each_nutrient_at_risk():
    bread = food({"valor_energetico": 100})
    milk = food({"valor_energetico": 60, "calcio": 120})

    result = analyze([(bread, 500)], catalog=[milk])

    assert result.top_sources[CALCIUM][0].food_id == milk.food_id
    assert result.top_sources[CALCIUM][0].amount_per_100_kcal == pytest.approx(200)


def catalog_by_id(foods):
    return {f.food_id: f for f in foods}
