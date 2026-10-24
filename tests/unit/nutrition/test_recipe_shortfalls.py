"""Final nutrition evaluation uses the reference profile and explicit tolerances."""

from dataclasses import replace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.domain.nutrition import (
    FoodComposition,
    GapaGroup,
    GapaPortion,
    Macronutrient,
    MacroRange,
    MealType,
    NutritionIndicators,
    RecipeRequest,
    StockedFood,
    UnmetConstraintKind,
)
from app.reference_data.nutrition_references import NINO_7_9
from app.services.nutrition.nutrition_service import NutritionService
from app.services.nutrition.shortfalls import (
    ENERGY_TOLERANCE_KCAL,
    MACRO_SHARE_TOLERANCE,
    evaluate_shortfalls,
)


def test_reference_profile_controls_final_macro_and_gapa_shortfalls():
    profile = replace(
        NINO_7_9,
        macro_ranges={Macronutrient.PROTEIN: MacroRange(0.2, 0.4)},
        gapa_portions={GapaGroup.DAIRY: GapaPortion(1, 200)},
    )
    indicators = NutritionIndicators(
        has_data=True,
        energy_kcal=1000,
        macro_energy_share={Macronutrient.PROTEIN: 0.19},
    )
    unmet, groups = evaluate_shortfalls([], {}, indicators, 1000, profile)
    assert groups == []
    assert unmet[0].kind == UnmetConstraintKind.MACRO_BELOW_MIN
    assert unmet[0].amount == pytest.approx(10)
    assert unmet[1].kind == UnmetConstraintKind.GAPA_GROUP_BELOW_MIN
    assert unmet[1].amount == pytest.approx(
        profile.gapa_minimum_per_1000_kcal(GapaGroup.DAIRY)
    )


def test_only_noise_within_named_tolerances_is_ignored():
    profile = replace(
        NINO_7_9,
        macro_ranges={Macronutrient.PROTEIN: MacroRange(0.2, 0.4)},
        gapa_portions={},
    )
    indicators = NutritionIndicators(
        has_data=True,
        energy_kcal=1000,
        macro_energy_share={Macronutrient.PROTEIN: 0.2 - MACRO_SHARE_TOLERANCE / 2},
    )
    assert (
        evaluate_shortfalls(
            [], {}, indicators, 1000 + ENERGY_TOLERANCE_KCAL / 2, profile
        )[0]
        == []
    )
    indicators.macro_energy_share[Macronutrient.PROTEIN] = (
        0.4 + MACRO_SHARE_TOLERANCE * 2
    )
    unmet, _ = evaluate_shortfalls([], {}, indicators, 1001, profile)
    assert {rule.kind for rule in unmet} == {
        UnmetConstraintKind.STOCK_INSUFFICIENT,
        UnmetConstraintKind.MACRO_ABOVE_MAX,
    }


@pytest.mark.parametrize("meal", list(MealType))
def test_target_energy_is_shared_without_database_access(meal):
    service = NutritionService(AsyncMock(), None)
    assert (
        service.target_energy_kcal(30, meal)
        == 30 * NINO_7_9.energy_kcal * NINO_7_9.meal_energy_fractions[meal]
    )


async def test_snapshot_solver_uses_only_requested_foods_without_database_access():
    uow = AsyncMock()
    service = NutritionService(uow, None)
    first, other = uuid4(), uuid4()
    foods = [
        StockedFood(FoodComposition(food_id, None, {"valor_energetico": 360}), 1000)
        for food_id in [first, other]
    ]
    solution = await service.maximize_stocked_recipe(
        RecipeRequest([first], 1, MealType.LUNCH), foods
    )
    assert solution.has_data
    assert {q.food_id for q in solution.quantities} == {first}
    assert solution.target_energy_kcal == service.target_energy_kcal(1, MealType.LUNCH)
    assert not uow.mock_calls
