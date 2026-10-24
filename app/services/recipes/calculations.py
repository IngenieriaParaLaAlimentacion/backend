from decimal import ROUND_DOWN, Decimal
from uuid import UUID

from app.domain.nutrition import (
    FoodQuantity,
    ReferenceProfile,
)
from app.schemas.recipes.recipe_schema import RecipeIngredient, RecipeProposal
from app.services.nutrition.compositions import composition_from_food
from app.services.nutrition.grams import CatalogGramsConverter
from app.services.nutrition.indicators import calculate_indicators
from app.services.nutrition.shortfalls import evaluate_shortfalls


def stock_ingredients(
    quantities: list[FoodQuantity], foods: dict, converter: CatalogGramsConverter
) -> list[RecipeIngredient]:
    """Convert solver grams to stock precision without rounding quantities up."""
    ingredients = []
    for item in quantities:
        food = foods[item.food_id]
        quantity = converter.from_grams(item.food_id, item.grams)
        if quantity is None:
            continue
        quantity = quantity.quantize(Decimal("0.001"), rounding=ROUND_DOWN)
        if quantity <= 0:
            continue
        grams = converter.to_grams(item.food_id, quantity)
        ingredients.append(
            RecipeIngredient(
                food_id=food.id,
                name=food.name,
                quantity=quantity,
                grams=grams,
                unit=food.base_unit,
            )
        )
    return ingredients


def calculate_proposal(
    proposal_id: UUID,
    portions: int,
    ingredients: list[RecipeIngredient],
    target: float,
    foods: dict,
    profile: ReferenceProfile,
    warnings: list[str],
    compositions: dict | None = None,
) -> RecipeProposal:
    """Calculate indicators and shortfalls for the final rounded ingredients."""
    quantities = [FoodQuantity(i.food_id, i.grams) for i in ingredients]
    compositions = (
        compositions
        if compositions is not None
        else {i.food_id: composition_from_food(foods[i.food_id]) for i in ingredients}
    )
    indicators = calculate_indicators(quantities, compositions, profile)
    energy = indicators.energy_kcal or 0
    unmet, groups = evaluate_shortfalls(
        quantities, compositions, indicators, target, profile
    )
    return RecipeProposal(
        id=proposal_id,
        name="",
        portions=portions,
        ingredients=ingredients,
        steps=[],
        indicators=indicators,
        nutrient_adequacy_percent={
            n.nutrient.value: n.adequacy_capped * 100 for n in indicators.nutrients
        },
        macronutrient_percent={
            m.value: share * 100 for m, share in indicators.macro_energy_share.items()
        },
        gapa_groups=groups,
        unmet_constraints=unmet,
        warnings=list(dict.fromkeys(warnings + indicators.warnings)),
        target_energy_kcal=target,
        energy_kcal=energy,
    )
