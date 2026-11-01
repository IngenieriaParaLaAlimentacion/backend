import uuid
from decimal import Decimal

import pytest

from app.domain.food_catalog import FoodNutrientRow
from app.domain.nutrition import GapaGroup
from app.exceptions.domain_exceptions import UnknownGapaGroupError
from app.services.nutrition.compositions import (
    compositions_from_rows,
    gapa_group_from_code,
)


def test_a_group_code_gives_its_group_and_no_code_gives_none():
    assert gapa_group_from_code("leche_yogur_y_quesos") == GapaGroup.DAIRY
    assert gapa_group_from_code(None) is None


def test_an_unknown_group_code_is_a_domain_error():
    with pytest.raises(UnknownGapaGroupError):
        gapa_group_from_code("not_a_group")


def test_rows_of_one_food_become_one_composition_with_its_group():
    food_id = uuid.uuid4()
    rows = [
        FoodNutrientRow(food_id, "carnes_y_huevos", "valor_energetico", Decimal("200")),
        FoodNutrientRow(food_id, "carnes_y_huevos", "hierro", Decimal("2.5")),
    ]

    composition = compositions_from_rows(rows)[food_id]

    assert composition.gapa_group == GapaGroup.MEAT_AND_EGGS
    assert composition.per_100g == {"valor_energetico": 200.0, "hierro": 2.5}
