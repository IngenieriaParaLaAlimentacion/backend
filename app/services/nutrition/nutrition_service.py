import asyncio
from datetime import datetime
from uuid import UUID

from app.core.interfaces.unit_of_work import IUnitOfWork
from app.domain.nutrition import (
    FoodComposition,
    FoodQuantity,
    GapaGroup,
    MonthlyIntakeAnalysis,
    NutritionIndicators,
    RecipeRequest,
    RecipeSolution,
)
from app.domain.user import UserActor
from app.models.food_catalog.food import Food
from app.reference_data.nutrition_references import NINO_7_9
from app.services.access import check_establishment_access
from app.services.nutrition.grams import GramsConverter
from app.services.nutrition.indicators import (
    calculate_indicators,
    required_nutrient_codes,
)
from app.services.nutrition.intake_analysis import (
    analyze_intake,
    compositions_from_rows,
    top_sources,
)
from app.services.nutrition.optimizer import StockedFood
from app.services.nutrition.optimizer import maximize_recipe as solve_recipe
from app.utils.dates import ARGENTINA_TZ


def composition_from_food(food: Food) -> FoodComposition:
    """Build a FoodComposition from a Food with its group and nutrient values loaded."""
    group = GapaGroup(food.gapa_category.code) if food.gapa_category else None
    return FoodComposition(
        food_id=food.id,
        gapa_group=group,
        per_100g={
            value.nutrient.code: float(value.amount_per_100g)
            for value in food.nutrient_values
        },
    )


def month_bounds(year: int, month: int) -> tuple[datetime, datetime]:
    """Return the start of the month and of the next one, in Buenos Aires time."""
    start = datetime(year, month, 1, tzinfo=ARGENTINA_TZ)
    end = (
        datetime(year + 1, 1, 1, tzinfo=ARGENTINA_TZ)
        if month == 12
        else datetime(year, month + 1, 1, tzinfo=ARGENTINA_TZ)
    )
    return start, end


class NutritionService:
    """Nutritional balance of food combinations, recipes and monthly intakes."""

    def __init__(self, uow: IUnitOfWork, grams: GramsConverter) -> None:
        self.uow = uow
        self.grams = grams

    async def calculate_indicators(
        self, items: list[FoodQuantity]
    ) -> NutritionIndicators:
        """Return the balance indicators of a list of foods in grams."""
        foods = await self.uow.food_repo.get_with_nutrients_by_ids(
            {item.food_id for item in items}
        )
        compositions = {food.id: composition_from_food(food) for food in foods}
        return calculate_indicators(items, compositions)

    async def maximize_recipe(
        self, establishment_id: UUID, request: RecipeRequest, actor: UserActor
    ) -> RecipeSolution:
        """Return the quantities that make the most balanced recipe the stock allows.

        The recipe feeds ``children_count`` children one ``meal_type`` of the daily
        energy. Only foods the establishment holds are used.

        Raises:
            EstablishmentNotFoundError: establishment_id does not exist.
            EstablishmentAccessDeniedError: field worker lacks approved access.
            ValueError: children_count is not positive.
        """
        if request.children_count <= 0:
            raise ValueError("children_count must be positive")
        await self.uow.establishment_repo.get_by_id_or_raise(establishment_id)
        await check_establishment_access(self.uow, actor, establishment_id)

        foods = await self.uow.food_repo.get_with_nutrients_by_ids(request.food_ids)
        stock = await self.uow.food_stock_repo.get_many(
            establishment_id, [food.id for food in foods]
        )
        stocked, without_conversion = [], 0
        for food in foods:
            if food.id not in stock:
                continue
            grams = self.grams.to_grams(food.id, stock[food.id])
            if grams is None:
                without_conversion += 1
            else:
                stocked.append(StockedFood(composition_from_food(food), grams))

        profile = NINO_7_9
        target = (
            request.children_count
            * profile.energy_kcal
            * profile.meal_energy_fractions[request.meal_type]
        )
        # CBC runs for a while, so it stays off the event loop.
        solution = await asyncio.to_thread(solve_recipe, stocked, target, profile)
        if without_conversion:
            solution.warnings.append(
                f"{without_conversion} food(s) have no conversion to grams and "
                "were left out"
            )
        return solution

    async def analyze_monthly_intake(
        self, establishment_id: UUID, year: int, month: int, actor: UserActor
    ) -> MonthlyIntakeAnalysis:
        """Return the balance of everything the establishment received in a month.

        Raises:
            EstablishmentNotFoundError: establishment_id does not exist.
            EstablishmentAccessDeniedError: field worker lacks approved access.
        """
        await self.uow.establishment_repo.get_by_id_or_raise(establishment_id)
        await check_establishment_access(self.uow, actor, establishment_id)

        start, end = month_bounds(year, month)
        received = await self.uow.food_intake_repo.sum_quantities_by_food(
            establishment_id, start, end
        )
        items, without_conversion = [], 0
        for food_id, quantity in received.items():
            grams = self.grams.to_grams(food_id, quantity)
            if grams is None:
                without_conversion += 1
            else:
                items.append(FoodQuantity(food_id, grams))

        foods = await self.uow.food_repo.get_with_nutrients_by_ids(
            [item.food_id for item in items]
        )
        analysis = analyze_intake(
            items, {food.id: composition_from_food(food) for food in foods}
        )
        if analysis.nutrients_at_risk:
            # The whole catalog is only read when there is a shortfall to cover.
            rows = await self.uow.food_repo.list_all_with_nutrients(
                required_nutrient_codes()
            )
            catalog = compositions_from_rows(rows)
            analysis.top_sources = {
                nutrient: top_sources(nutrient, catalog)
                for nutrient in analysis.nutrients_at_risk
            }
        if without_conversion:
            analysis.warnings.append(
                f"{without_conversion} food(s) have no conversion to grams and "
                "were left out"
            )
        return analysis
