from collections.abc import Iterable
from uuid import UUID

from app.domain.food_catalog import FoodNutrientRow
from app.domain.nutrition import FoodComposition, GapaGroup
from app.exceptions.domain_exceptions import UnknownGapaGroupError
from app.models.food_catalog.food import Food


def gapa_group_from_code(code: str | None) -> GapaGroup | None:
    """Return the GAPA group with this code, or None for a food with no group.

    Raises:
        UnknownGapaGroupError: the code is not one of the six GAPA groups.
    """
    if code is None:
        return None
    try:
        return GapaGroup(code)
    except ValueError:
        raise UnknownGapaGroupError(code) from None


def composition_from_food(food: Food) -> FoodComposition:
    """Build a FoodComposition from a Food with its group and nutrient values loaded."""
    group = food.gapa_category.code if food.gapa_category else None
    return FoodComposition(
        food_id=food.id,
        gapa_group=gapa_group_from_code(group),
        per_100g={
            value.nutrient.code: float(value.amount_per_100g)
            for value in food.nutrient_values
        },
    )


def compositions_from_rows(
    rows: Iterable[FoodNutrientRow],
) -> dict[UUID, FoodComposition]:
    """Group (food, nutrient) rows into one composition per food."""
    compositions: dict[UUID, FoodComposition] = {}
    for row in rows:
        composition = compositions.get(row.food_id)
        if composition is None:
            composition = FoodComposition(
                row.food_id, gapa_group_from_code(row.gapa_category_code), {}
            )
            compositions[row.food_id] = composition
        composition.per_100g[row.nutrient_code] = float(row.amount_per_100g)
    return compositions
