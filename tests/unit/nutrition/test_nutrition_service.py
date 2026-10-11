import uuid
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.food_catalog import FoodNutrientRow
from app.domain.nutrition import (
    FoodQuantity,
    MealType,
    PrioritizedNutrient,
    RecipeRequest,
)
from app.domain.user import UserActor, UserRole
from app.exceptions.domain_exceptions import (
    EstablishmentAccessDeniedError,
    InvalidChildrenCountError,
)
from app.reference_data.nutrition_references import NINO_7_9
from app.services.nutrition import NutritionService
from app.services.nutrition.nutrition_service import month_bounds

ESTABLISHMENT_ID = uuid.uuid4()
ADMIN = UserActor(user_id=uuid.uuid4(), role=UserRole.ADMIN)


class GramsPerUnit:
    """Converter that weighs every unit of a food as ``factor`` grams, or knows
    nothing about the foods listed in ``unknown``."""

    def __init__(self, factor: float = 1000, unknown: frozenset = frozenset()):
        self.factor = factor
        self.unknown = unknown

    def to_grams(self, food_id, quantity: Decimal):
        return None if food_id in self.unknown else float(quantity) * self.factor

    def from_grams(self, food_id, grams: float):
        raise NotImplementedError


def food_with(food_id, per_100g: dict[str, float]):
    """A loaded Food, as the repository returns it."""
    food = MagicMock()
    food.id = food_id
    food.gapa_category = None
    food.nutrient_values = [
        MagicMock(nutrient=MagicMock(code=code), amount_per_100g=Decimal(str(amount)))
        for code, amount in per_100g.items()
    ]
    return food


def make_uow(received=None, foods=(), rows=(), stock=None):
    uow = AsyncMock()
    uow.food_intake_repo.sum_quantities_by_food = AsyncMock(return_value=received or {})
    uow.food_repo.get_with_nutrients_by_ids = AsyncMock(return_value=list(foods))
    uow.food_repo.list_all_with_nutrients = AsyncMock(return_value=list(rows))
    uow.food_stock_repo.get_many = AsyncMock(return_value=stock or {})
    return uow


@pytest.mark.parametrize(
    ("year", "month", "start", "end"),
    [
        (2026, 3, (2026, 3, 1), (2026, 4, 1)),
        (2026, 12, (2026, 12, 1), (2027, 1, 1)),
    ],
)
def test_month_is_counted_in_buenos_aires_time(year, month, start, end):
    first, after = month_bounds(year, month)

    # Buenos Aires is three hours behind UTC all year.
    assert first == datetime(*start, 3, tzinfo=timezone.utc)
    assert after == datetime(*end, 3, tzinfo=timezone.utc)


async def test_monthly_analysis_asks_the_repository_for_the_month_window():
    uow = make_uow()

    await NutritionService(uow, GramsPerUnit()).analyze_monthly_intake(
        ESTABLISHMENT_ID, 2026, 3, ADMIN
    )

    start, end = month_bounds(2026, 3)
    uow.food_intake_repo.sum_quantities_by_food.assert_awaited_once_with(
        ESTABLISHMENT_ID, start, end
    )


async def test_monthly_analysis_without_intakes_has_no_data():
    result = await NutritionService(make_uow(), GramsPerUnit()).analyze_monthly_intake(
        ESTABLISHMENT_ID, 2026, 3, ADMIN
    )

    assert not result.has_data
    assert result.nutrients_at_risk == []


async def test_monthly_analysis_converts_quantities_to_grams_before_calculating():
    rice_id = uuid.uuid4()
    # 2 kg of rice at 100 kcal per 100 g: 2,000 g give 2,000 kcal.
    uow = make_uow(
        received={rice_id: Decimal("2")},
        foods=[food_with(rice_id, {"valor_energetico": 100})],
        rows=[FoodNutrientRow(rice_id, None, "valor_energetico", Decimal("100"))],
    )

    result = await NutritionService(uow, GramsPerUnit()).analyze_monthly_intake(
        ESTABLISHMENT_ID, 2026, 3, ADMIN
    )

    assert result.indicators.energy_kcal == pytest.approx(2000)


async def test_food_without_known_conversion_is_left_out_and_reported():
    rice_id, mystery_id = uuid.uuid4(), uuid.uuid4()
    uow = make_uow(
        received={rice_id: Decimal("1"), mystery_id: Decimal("5")},
        foods=[food_with(rice_id, {"valor_energetico": 100})],
    )
    grams = GramsPerUnit(unknown=frozenset({mystery_id}))

    result = await NutritionService(uow, grams).analyze_monthly_intake(
        ESTABLISHMENT_ID, 2026, 3, ADMIN
    )

    assert result.indicators.energy_kcal == pytest.approx(1000)
    assert any("conversion" in warning for warning in result.warnings)


async def test_field_worker_without_approved_access_cannot_analyze():
    uow = make_uow()
    uow.user_establishment_repo.get_relation = AsyncMock(return_value=None)
    worker = UserActor(user_id=uuid.uuid4(), role=UserRole.FIELD_WORKER)

    with pytest.raises(EstablishmentAccessDeniedError):
        await NutritionService(uow, GramsPerUnit()).analyze_monthly_intake(
            ESTABLISHMENT_ID, 2026, 3, worker
        )

    uow.food_intake_repo.sum_quantities_by_food.assert_not_awaited()


async def test_calculate_indicators_loads_the_foods_and_computes_them():
    rice_id = uuid.uuid4()
    uow = make_uow(foods=[food_with(rice_id, {"valor_energetico": 130})])

    result = await NutritionService(uow, GramsPerUnit()).calculate_indicators(
        [FoodQuantity(rice_id, 200)]
    )

    assert result.energy_kcal == pytest.approx(260)


async def test_catalog_is_only_read_when_a_nutrient_is_at_risk():
    rice_id = uuid.uuid4()
    # 100 kcal per 100 g and no calcium: calcium is at risk, so it is read.
    uow = make_uow(
        received={rice_id: Decimal("1")},
        foods=[food_with(rice_id, {"valor_energetico": 100})],
        rows=[],
    )
    await NutritionService(uow, GramsPerUnit()).analyze_monthly_intake(
        ESTABLISHMENT_ID, 2026, 3, ADMIN
    )
    uow.food_repo.list_all_with_nutrients.assert_awaited_once()

    empty = make_uow()
    await NutritionService(empty, GramsPerUnit()).analyze_monthly_intake(
        ESTABLISHMENT_ID, 2026, 3, ADMIN
    )
    empty.food_repo.list_all_with_nutrients.assert_not_awaited()


async def test_each_nutrient_at_risk_gets_its_best_sources_from_the_catalog():
    bread_id, milk_id = uuid.uuid4(), uuid.uuid4()
    uow = make_uow(
        received={bread_id: Decimal("1")},
        foods=[food_with(bread_id, {"valor_energetico": 100})],
        rows=[
            FoodNutrientRow(
                milk_id, "leche_yogur_y_quesos", "valor_energetico", Decimal("60")
            ),
            FoodNutrientRow(milk_id, "leche_yogur_y_quesos", "calcio", Decimal("120")),
        ],
    )

    result = await NutritionService(uow, GramsPerUnit()).analyze_monthly_intake(
        ESTABLISHMENT_ID, 2026, 3, ADMIN
    )

    best = result.top_sources[PrioritizedNutrient.CALCIUM][0]
    assert best.food_id == milk_id
    assert best.amount_per_100_kcal == pytest.approx(200)


async def test_recipe_target_is_the_meal_share_of_the_energy_of_every_child():
    rice_id = uuid.uuid4()
    uow = make_uow(
        foods=[food_with(rice_id, {"valor_energetico": 100})],
        stock={rice_id: Decimal("1000")},  # 1,000 kg: never the limit
    )
    request = RecipeRequest([rice_id], children_count=10, meal_type=MealType.LUNCH)

    result = await NutritionService(uow, GramsPerUnit()).maximize_recipe(
        ESTABLISHMENT_ID, request, ADMIN
    )

    assert result.target_energy_kcal == pytest.approx(10 * 1770 * 0.35)
    assert result.energy_kcal == pytest.approx(10 * 1770 * 0.35)


async def test_recipe_only_uses_foods_the_establishment_holds_in_grams():
    rice_id, absent_id = uuid.uuid4(), uuid.uuid4()
    uow = make_uow(
        foods=[
            food_with(rice_id, {"valor_energetico": 100}),
            food_with(absent_id, {"valor_energetico": 100}),
        ],
        stock={rice_id: Decimal("2")},  # 2 kg: 2,000 g hold 2,000 kcal
    )
    request = RecipeRequest(
        [rice_id, absent_id], children_count=100, meal_type=MealType.LUNCH
    )

    result = await NutritionService(uow, GramsPerUnit()).maximize_recipe(
        ESTABLISHMENT_ID, request, ADMIN
    )

    assert [q.food_id for q in result.quantities] == [rice_id]
    assert result.energy_kcal == pytest.approx(2000)


async def test_recipe_without_children_is_rejected():
    request = RecipeRequest([uuid.uuid4()], children_count=0, meal_type=MealType.LUNCH)

    with pytest.raises(InvalidChildrenCountError):
        await NutritionService(make_uow(), GramsPerUnit()).maximize_recipe(
            ESTABLISHMENT_ID, request, ADMIN
        )


async def test_field_worker_without_approved_access_cannot_build_a_recipe():
    uow = make_uow()
    uow.user_establishment_repo.get_relation = AsyncMock(return_value=None)
    worker = UserActor(user_id=uuid.uuid4(), role=UserRole.FIELD_WORKER)
    request = RecipeRequest([uuid.uuid4()], children_count=5, meal_type=MealType.LUNCH)

    with pytest.raises(EstablishmentAccessDeniedError):
        await NutritionService(uow, GramsPerUnit()).maximize_recipe(
            ESTABLISHMENT_ID, request, worker
        )

    uow.food_stock_repo.get_many.assert_not_awaited()


async def test_recipe_target_follows_the_profile_the_service_was_given():
    rice_id = uuid.uuid4()
    uow = make_uow(
        foods=[food_with(rice_id, {"valor_energetico": 100})],
        stock={rice_id: Decimal("1000")},
    )
    profile = replace(NINO_7_9, energy_kcal=1000)
    request = RecipeRequest([rice_id], children_count=10, meal_type=MealType.LUNCH)

    result = await NutritionService(uow, GramsPerUnit(), profile).maximize_recipe(
        ESTABLISHMENT_ID, request, ADMIN
    )

    assert result.target_energy_kcal == pytest.approx(10 * 1000 * 0.35)
