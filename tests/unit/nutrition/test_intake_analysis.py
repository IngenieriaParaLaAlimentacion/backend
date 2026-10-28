import pytest

from app.domain.nutrition import (
    FoodQuantity,
    GapaGroup,
    Macronutrient,
    PrioritizedNutrient,
)
from app.services.nutrition.intake_analysis import analyze_intake, top_sources
from tests.unit.nutrition.helpers import composition

CALCIUM = PrioritizedNutrient.CALCIUM


def analyze(received):
    items = [FoodQuantity(f.food_id, grams) for f, grams in received]
    compositions = {f.food_id: f for f, _ in received}
    return analyze_intake(items, compositions)


# The calcium reference is 395 mg per 1,000 kcal, so two thirds of it is 264.
@pytest.mark.parametrize(
    ("calcium_per_100_kcal", "at_risk"),
    [(20, True), (30, False)],
)
def test_nutrient_below_two_thirds_of_its_reference_is_at_risk(
    calcium_per_100_kcal, at_risk
):
    bread = composition({"valor_energetico": 100, "calcio": calcium_per_100_kcal})

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
    rice = composition({"valor_energetico": 100, "carbohidratos_disponibles": 25})

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
    veg = composition({"valor_energetico": 50}, GapaGroup.FRUITS_AND_VEGETABLES)

    result = analyze([(veg, 100)])

    assert GapaGroup.OPTIONAL not in result.missing_gapa_groups
    assert set(result.missing_gapa_groups) == set(GapaGroup) - {
        GapaGroup.FRUITS_AND_VEGETABLES,
        GapaGroup.OPTIONAL,
    }


def test_sources_are_ranked_by_amount_per_100_kcal_and_limited_to_the_count():
    catalog = [
        composition({"valor_energetico": 100, "calcio": c}, GapaGroup.DAIRY)
        for c in range(10, 100, 10)
    ]

    ranked = top_sources(CALCIUM, catalog_by_id(catalog), count=3)

    assert [round(s.amount_per_100_kcal) for s in ranked] == [90, 80, 70]


def test_sources_skip_optional_ungrouped_and_energyless_foods():
    good = composition({"valor_energetico": 100, "calcio": 10}, GapaGroup.DAIRY)
    candidates = [
        good,
        composition({"valor_energetico": 100, "calcio": 500}, GapaGroup.OPTIONAL),
        composition({"valor_energetico": 100, "calcio": 500}, None),
        composition({"valor_energetico": 0, "calcio": 500}, GapaGroup.DAIRY),
        composition({"valor_energetico": 100}, GapaGroup.DAIRY),
    ]

    ranked = top_sources(CALCIUM, catalog_by_id(candidates))

    assert [s.food_id for s in ranked] == [good.food_id]


def test_a_food_in_several_cooking_states_is_suggested_once_in_its_best_one():
    def liver(name, calcium):
        return composition(
            {"valor_energetico": 100, "calcio": calcium}, GapaGroup.MEAT_AND_EGGS, name
        )

    best = liver("Hígado (rehogado/plancha)", 90)
    candidates = [
        best,
        liver("Hígado, crudo", 80),
        liver("Hígado de pollo, crudo", 70),
        liver("Hígado de pollo, cocido", 60),
        liver("Pulpo, crudo", 50),
    ]

    ranked = top_sources(CALCIUM, catalog_by_id(candidates))

    assert [round(s.amount_per_100_kcal) for s in ranked] == [90, 70, 50]
    assert ranked[0].food_id == best.food_id


def test_foods_that_differ_beyond_the_cooking_state_are_all_suggested():
    candidates = [
        composition({"valor_energetico": 100, "calcio": 90}, GapaGroup.DAIRY, name)
        for name in (
            "Leche entera fluida, fortificada con hierro",
            "Leche entera fluida, con vitaminas A y D",
            "Papa, prefrita",
        )
    ]

    ranked = top_sources(CALCIUM, catalog_by_id(candidates))

    assert len(ranked) == 3


def test_warnings_of_the_analysis_do_not_alias_those_of_the_indicators():
    rice = composition({"valor_energetico": 100})

    result = analyze([(rice, 100)])
    result.warnings.append("added later")

    assert "added later" not in result.indicators.warnings


def catalog_by_id(foods):
    return {f.food_id: f for f in foods}
