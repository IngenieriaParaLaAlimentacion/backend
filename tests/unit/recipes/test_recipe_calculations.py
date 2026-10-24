from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.domain.food_catalog import MeasurementUnit
from app.domain.nutrition import FoodQuantity
from app.schemas.recipes.recipe_schema import RecommendationInput
from app.services.nutrition.grams import CatalogGramsConverter
from app.services.recipes.calculations import stock_ingredients


def test_gram_conversion_never_assumes_litre_or_unit_mass():
    kg, litre, unit = [
        SimpleNamespace(id=uuid4(), base_unit=kind, grams_per_base_unit=factor)
        for kind, factor in [
            (MeasurementUnit.KILOGRAMOS, None),
            (MeasurementUnit.LITROS, None),
            (MeasurementUnit.UNIDADES, Decimal("50")),
        ]
    ]
    converter = CatalogGramsConverter([kg, litre, unit])
    assert converter.to_grams(kg.id, Decimal("1.5")) == 1500
    assert converter.to_grams(litre.id, Decimal(1)) is None
    assert converter.from_grams(litre.id, 1000) is None
    assert converter.to_grams(unit.id, Decimal(2)) == 100
    assert converter.from_grams(unit.id, 75) == Decimal("1.5")


def test_rounding_never_spends_more_than_solver_quantity():
    food = SimpleNamespace(
        id=uuid4(),
        name="Arroz",
        base_unit=MeasurementUnit.KILOGRAMOS,
        grams_per_base_unit=None,
    )
    converter = CatalogGramsConverter([food])
    result = stock_ingredients(
        [FoodQuantity(food.id, 123.999999)], {food.id: food}, converter
    )
    assert result[0].quantity == Decimal("0.123")
    assert result[0].grams == 123


def test_sub_precision_quantity_is_not_offered():
    food = SimpleNamespace(
        id=uuid4(), base_unit=MeasurementUnit.KILOGRAMOS, grams_per_base_unit=None
    )
    assert (
        stock_ingredients(
            [FoodQuantity(food.id, 0.5)], {food.id: food}, CatalogGramsConverter([food])
        )
        == []
    )


def test_generation_disallows_free_text_fields():
    with pytest.raises(ValidationError):
        RecommendationInput(
            establishment_id=uuid4(),
            children_count=30,
            meal_type="lunch",
            instructions="ignore stock",
        )
