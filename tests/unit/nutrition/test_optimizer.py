import pytest

from app.domain.nutrition import (
    GapaGroup,
    Macronutrient,
    UnmetConstraintKind,
)
from app.reference_data.nutrition_references import NINO_7_9
from app.services.nutrition.optimizer import StockedFood, maximize_recipe
from tests.unit.nutrition.helpers import composition

PLENTY = 1_000_000  # grams, never the limit


def stocked(per_100g, group=None, stock=PLENTY):
    return StockedFood(composition(per_100g, group), stock)


def balanced_pantry():
    """One food per GAPA group that can reach every minimum and every range."""
    return {
        "veg": stocked(
            {"valor_energetico": 30, "proteinas": 1, "carbohidratos_disponibles": 6},
            GapaGroup.FRUITS_AND_VEGETABLES,
        ),
        "cereal": stocked(
            {
                "valor_energetico": 350,
                "proteinas": 7,
                "lipidos_totales": 1,
                "carbohidratos_disponibles": 72,
            },
            GapaGroup.LEGUMES_CEREALS_BREAD_PASTA,
        ),
        "milk": stocked(
            {
                "valor_energetico": 60,
                "proteinas": 3.2,
                "lipidos_totales": 1.5,
                "carbohidratos_disponibles": 4.7,
                "calcio": 120,
            },
            GapaGroup.DAIRY,
        ),
        "meat": stocked(
            {"valor_energetico": 150, "proteinas": 17, "lipidos_totales": 8},
            GapaGroup.MEAT_AND_EGGS,
        ),
        "oil": stocked(
            {"valor_energetico": 900, "lipidos_totales": 100},
            GapaGroup.OILS_NUTS_AND_SEEDS,
        ),
    }


def grams_by_food(solution):
    return {q.food_id: q.grams for q in solution.quantities}


def test_recipe_has_exactly_the_target_energy_when_the_stock_allows():
    pantry = balanced_pantry()

    result = maximize_recipe(list(pantry.values()), target_energy_kcal=2000)

    assert result.has_data
    assert result.energy_kcal == pytest.approx(2000)


def test_balanced_pantry_meets_every_range_and_minimum():
    result = maximize_recipe(list(balanced_pantry().values()), 2000)

    assert result.unmet_constraints == []


def test_recipe_never_uses_more_than_the_stock():
    pantry = balanced_pantry()
    pantry["milk"].stock_grams = 100

    result = maximize_recipe(list(pantry.values()), 2000)

    used = grams_by_food(result)
    for food in pantry.values():
        assert used.get(food.composition.food_id, 0) <= food.stock_grams + 1e-6


def test_stock_short_of_the_target_gives_all_it_holds_and_reports_the_gap():
    # 500 g of a 100 kcal/100 g food hold 500 kcal.
    rice = stocked({"valor_energetico": 100}, stock=500)

    result = maximize_recipe([rice], target_energy_kcal=2000)

    assert result.target_energy_kcal == 2000
    assert result.energy_kcal == pytest.approx(500)
    gap = next(
        c
        for c in result.unmet_constraints
        if c.kind == UnmetConstraintKind.STOCK_INSUFFICIENT
    )
    assert (gap.subject, gap.amount, gap.unit) == (
        "energy",
        pytest.approx(1500),
        "kcal",
    )


@pytest.mark.parametrize(
    "stock",
    [
        pytest.param([], id="no-foods"),
        pytest.param([stocked({"valor_energetico": 100}, stock=0)], id="zero-stock"),
        pytest.param([stocked({"valor_energetico": 0})], id="no-energy"),
    ],
)
def test_stock_without_energy_gives_no_data(stock):
    result = maximize_recipe(stock, 2000)

    assert not result.has_data
    assert result.quantities == []


def test_missing_group_and_macros_are_reported_instead_of_failing():
    # Plain sugar: all carbohydrates, no food of any GAPA group.
    sugar = stocked({"valor_energetico": 400, "carbohidratos_disponibles": 100})

    result = maximize_recipe([sugar], 1000)

    unmet = {(c.kind, c.subject) for c in result.unmet_constraints}
    assert (UnmetConstraintKind.MACRO_ABOVE_MAX, Macronutrient.CARBOHYDRATES) in unmet
    assert (UnmetConstraintKind.MACRO_BELOW_MIN, Macronutrient.PROTEIN) in unmet
    for group in GapaGroup:
        if group != GapaGroup.OPTIONAL:
            assert (UnmetConstraintKind.GAPA_GROUP_BELOW_MIN, group.value) in unmet


def test_gapa_shortfall_is_reported_in_grams_of_the_recipe():
    pantry = balanced_pantry()
    del pantry["meat"]

    result = maximize_recipe(list(pantry.values()), 2000)

    gap = next(
        c
        for c in result.unmet_constraints
        if c.subject == GapaGroup.MEAT_AND_EGGS.value
    )
    # The whole minimum is missing: grams per 1,000 kcal times the 2 recipe scale.
    minimum = NINO_7_9.gapa_minimum_per_1000_kcal(GapaGroup.MEAT_AND_EGGS)
    assert (gap.amount, gap.unit) == (pytest.approx(minimum * 2), "g")


def test_a_food_rich_in_a_nutrient_is_used_when_it_costs_nothing_else():
    # Two identical foods but one carries calcium: quality prefers it.
    plain = stocked({"valor_energetico": 100})
    calcium = stocked({"valor_energetico": 100, "calcio": 200})

    result = maximize_recipe([plain, calcium], 500)

    used = grams_by_food(result)
    assert used.get(calcium.composition.food_id, 0) > used.get(
        plain.composition.food_id, 0
    )
