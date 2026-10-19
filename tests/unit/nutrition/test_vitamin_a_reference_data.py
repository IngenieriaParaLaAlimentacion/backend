from collections import defaultdict

from tests.unit.nutrition.helpers import read_reference_csv


def test_no_food_has_more_retinol_than_vitamin_a_rae():
    # Retinol is part of the RAE. More retinol than RAE would give a negative
    # vitamin A in retinol equivalents (2 x RAE - retinol) and no feasible recipe.
    readings = defaultdict(dict)
    for row in read_reference_csv("food_nutrient_values.csv"):
        if row["nutrient_code"] in ("vitamina_a_rae", "retinol"):
            readings[row["food_code"]][row["nutrient_code"]] = float(
                row["amount_per_100g"]
            )

    offenders = [
        food
        for food, amounts in readings.items()
        if amounts.get("retinol", 0.0) > amounts.get("vitamina_a_rae", float("inf"))
    ]

    assert offenders == []
