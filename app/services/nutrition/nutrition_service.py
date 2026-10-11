import asyncio
from collections.abc import Mapping
from decimal import Decimal
from uuid import UUID

from app.core.interfaces.unit_of_work import IUnitOfWork
from app.domain.nutrition import (
    FoodQuantity,
    MonthlyIntakeAnalysis,
    NutritionIndicators,
    RecipeRequest,
    RecipeSolution,
    StockedFood,
)
from app.domain.user import UserActor
from app.exceptions.domain_exceptions import InvalidChildrenCountError
from app.reference_data.nutrition_references import NINO_7_9, ReferenceProfile
from app.services.access import check_establishment_access
from app.services.nutrition.compositions import (
    composition_from_food,
    compositions_from_rows,
)
from app.services.nutrition.grams import GramsConverter
from app.services.nutrition.indicators import (
    calculate_indicators,
    required_nutrient_codes,
)
from app.services.nutrition.intake_analysis import (
    analyze_intake,
    top_sources,
)
from app.services.nutrition.optimizer import maximize_recipe as solve_recipe
from app.utils.dates import month_bounds


class NutritionService:
    """Nutritional balance of food combinations, recipes and monthly intakes."""

    def __init__(
        self,
        uow: IUnitOfWork,
        grams: GramsConverter,
        profile: ReferenceProfile = NINO_7_9,
    ) -> None:
        self.uow = uow
        self.grams = grams
        self.profile = profile

    async def _resolve_establishment(
        self, establishment_id: UUID, actor: UserActor
    ) -> None:
        """Confirm the establishment exists and the actor may look at it."""
        await self.uow.establishment_repo.get_by_id_or_raise(establishment_id)
        await check_establishment_access(self.uow, actor, establishment_id)

    def _to_grams(
        self, quantities: Mapping[UUID, Decimal]
    ) -> tuple[dict[UUID, float], str | None]:
        """Convert quantities in each food's base unit to grams.

        Returns the grams per food and a warning naming how many foods were left
        out for having no known conversion, or None when every food converted.
        """
        grams: dict[UUID, float] = {}
        for food_id, quantity in quantities.items():
            converted = self.grams.to_grams(food_id, quantity)
            if converted is not None:
                grams[food_id] = converted
        left_out = len(quantities) - len(grams)
        warning = (
            f"{left_out} food(s) have no conversion to grams and were left out"
            if left_out
            else None
        )
        return grams, warning

    async def calculate_indicators(
        self, items: list[FoodQuantity]
    ) -> NutritionIndicators:
        """Return the balance indicators of a list of foods in grams."""
        foods = await self.uow.food_repo.get_with_nutrients_by_ids(
            {item.food_id for item in items}
        )
        compositions = {food.id: composition_from_food(food) for food in foods}
        return calculate_indicators(items, compositions, self.profile)

    async def maximize_recipe(
        self, establishment_id: UUID, request: RecipeRequest, actor: UserActor
    ) -> RecipeSolution:
        """Return the quantities that make the most balanced recipe the stock allows.

        The recipe feeds ``children_count`` children one ``meal_type`` of the daily
        energy. Only foods the establishment holds are used.

        Raises:
            EstablishmentNotFoundError: establishment_id does not exist.
            EstablishmentAccessDeniedError: field worker lacks approved access.
            InvalidChildrenCountError: children_count is not positive.
        """
        if request.children_count <= 0:
            raise InvalidChildrenCountError(request.children_count)
        await self._resolve_establishment(establishment_id, actor)

        foods = await self.uow.food_repo.get_with_nutrients_by_ids(request.food_ids)
        stock = await self.uow.food_stock_repo.get_many(
            establishment_id, [food.id for food in foods]
        )
        stock_grams, warning = self._to_grams(stock)
        stocked = [
            StockedFood(composition_from_food(food), stock_grams[food.id])
            for food in foods
            if food.id in stock_grams
        ]

        target = (
            request.children_count
            * self.profile.energy_kcal
            * self.profile.meal_energy_fractions[request.meal_type]
        )
        # The solver is CPU-bound, so it stays off the event loop.
        solution = await asyncio.to_thread(solve_recipe, stocked, target, self.profile)
        if warning:
            solution.warnings.append(warning)
        return solution

    async def analyze_monthly_intake(
        self, establishment_id: UUID, year: int, month: int, actor: UserActor
    ) -> MonthlyIntakeAnalysis:
        """Return the balance of everything the establishment received in a month.

        Raises:
            EstablishmentNotFoundError: establishment_id does not exist.
            EstablishmentAccessDeniedError: field worker lacks approved access.
        """
        await self._resolve_establishment(establishment_id, actor)

        start, end = month_bounds(year, month)
        received = await self.uow.food_intake_repo.sum_quantities_by_food(
            establishment_id, start, end
        )
        grams, warning = self._to_grams(received)
        items = [FoodQuantity(food_id, amount) for food_id, amount in grams.items()]

        foods = await self.uow.food_repo.get_with_nutrients_by_ids(
            [item.food_id for item in items]
        )
        analysis = analyze_intake(
            items,
            {food.id: composition_from_food(food) for food in foods},
            self.profile,
        )
        if analysis.nutrients_at_risk:
            # The whole catalog is only read when there is a shortfall to cover.
            rows = await self.uow.food_repo.list_all_with_nutrients(
                required_nutrient_codes(self.profile)
            )
            catalog = compositions_from_rows(rows)
            analysis.top_sources = {
                nutrient: top_sources(nutrient, catalog)
                for nutrient in analysis.nutrients_at_risk
            }
        if warning:
            analysis.warnings.append(warning)
        return analysis
