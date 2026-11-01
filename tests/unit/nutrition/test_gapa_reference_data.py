from app.domain.nutrition import GapaGroup
from tests.unit.nutrition.helpers import read_reference_csv


def test_gapa_group_codes_match_the_reference_data():
    codes = {row["code"] for row in read_reference_csv("gapa_food_categories.csv")}

    assert codes == {group.value for group in GapaGroup}


def test_every_food_group_exists_in_the_gapa_categories():
    codes = {row["code"] for row in read_reference_csv("gapa_food_categories.csv")}
    assigned = {row["gapa_category"] for row in read_reference_csv("foods.csv")} - {""}

    assert assigned <= codes


def test_only_foods_without_energy_may_lack_a_gapa_group():
    # A food with energy but no group would drop out of the energy share by group.
    energy = {
        row["food_code"]: float(row["amount_per_100g"])
        for row in read_reference_csv("food_nutrient_values.csv")
        if row["nutrient_code"] == "valor_energetico"
    }
    ungrouped_with_energy = [
        row["code"]
        for row in read_reference_csv("foods.csv")
        if not row["gapa_category"] and energy[row["code"]] > 0
    ]

    assert ungrouped_with_energy == []
