from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.domain.food_catalog import MeasurementUnit
from app.domain.nutrition import FoodQuantity
from app.domain.unit_conversion import ConversionFactors
from app.schemas.recipes.recipe_schema import RecommendationInput
from app.services.nutrition.grams import GramsConverter
from app.services.recipes.calculations import stock_ingredients


def test_rounding_never_spends_more_than_solver_quantity():
    food = SimpleNamespace(
        id=uuid4(), name="Arroz", base_unit=MeasurementUnit.KILOGRAMOS
    )
    converter = GramsConverter(
        {food.id: food.base_unit}, {food.id: ConversionFactors()}
    )
    result = stock_ingredients(
        [FoodQuantity(food.id, 123.999999)], {food.id: food}, converter
    )
    assert result[0].quantity == Decimal("0.123")
    assert result[0].grams == 123


def test_sub_precision_quantity_is_not_offered():
    food = SimpleNamespace(id=uuid4(), base_unit=MeasurementUnit.KILOGRAMOS)
    converter = GramsConverter(
        {food.id: food.base_unit}, {food.id: ConversionFactors()}
    )
    assert (
        stock_ingredients([FoodQuantity(food.id, 0.5)], {food.id: food}, converter)
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
