import asyncio
from collections.abc import Iterable, Mapping
from decimal import Decimal
from uuid import UUID

from app.core.interfaces.unit_of_work import IUnitOfWork
from app.domain.nutrition import (
    FoodQuantity,
    MealType,
    MonthlyIntakeAnalysis,
    NutritionIndicators,
    RecipeRequest,
    RecipeSolution,
    ReferenceProfile,
    StockedFood,
)
from app.domain.unit_conversion import ConversionFailure, Converted
from app.domain.user import UserActor
from app.exceptions.domain_exceptions import InvalidChildrenCountError
from app.models.food_catalog.food import Food
from app.reference_data.nutrition_references import NINO_7_9
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

# What a food left out of a calculation lacks, by the reason it was not converted.
_FAILURE_REASONS: dict[ConversionFailure, str] = {
    ConversionFailure.MISSING_DENSITY: "no density",
    ConversionFailure.MISSING_UNIT_WEIGHT: "no unit weight",
    ConversionFailure.UNSUPPORTED_UNIT: "no supported unit",
}


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

    async def _to_grams(
        self, quantities: Mapping[UUID, Decimal], foods: Iterable[Food]
    ) -> tuple[dict[UUID, float], list[str]]:
        """Convert quantities in each food's base unit to grams.

        ``foods`` holds every food in ``quantities``. Returns the grams per food
        and one warning per food left out, naming it and the factor it lacks.
        """
        by_id = {food.id: food for food in foods}
        results = await self.grams.to_grams(
            quantities, {food_id: by_id[food_id].base_unit for food_id in quantities}
        )
        grams: dict[UUID, float] = {}
        warnings: list[str] = []
        for food_id, result in results.items():
            if isinstance(result, Converted):
                # The solver and indicators work in floats; exact decimals only
                # matter for stored quantities, not for estimating nutrients.
                grams[food_id] = float(result.value)
            else:
                warnings.append(
                    f"{by_id[food_id].name} left out: "
                    f"{_FAILURE_REASONS[result.reason]} to convert it to grams"
                )
        return grams, warnings

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
        stock_grams, warnings = await self._to_grams(stock, foods)
        stocked = [
            StockedFood(composition_from_food(food), stock_grams[food.id])
            for food in foods
            if food.id in stock_grams
        ]

        return await self.maximize_stocked_recipe(request, stocked, warnings)

    def target_energy_kcal(self, children_count: int, meal_type: MealType) -> float:
        """Return the reference meal energy for this number of children."""
        if children_count <= 0:
            raise InvalidChildrenCountError(children_count)
        return (
            children_count
            * self.profile.energy_kcal
            * self.profile.meal_energy_fractions[meal_type]
        )

    async def maximize_stocked_recipe(
        self,
        request: RecipeRequest,
        stocked: list[StockedFood],
        warnings: Iterable[str] = (),
    ) -> RecipeSolution:
        """Optimize an authorized, already-loaded stock snapshot without DB reads.

        The caller owns access checks and snapshot consistency. This internal
        service operation is not an alternative HTTP authorization boundary.
        """
        target = self.target_energy_kcal(request.children_count, request.meal_type)
        selected = set(request.food_ids)
        solution = await asyncio.to_thread(
            solve_recipe,
            [food for food in stocked if food.composition.food_id in selected],
            target,
            self.profile,
        )
        solution.warnings.extend(warnings)
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
        foods = await self.uow.food_repo.get_with_nutrients_by_ids(list(received))
        grams, warnings = await self._to_grams(received, foods)
        items = [FoodQuantity(food_id, amount) for food_id, amount in grams.items()]

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
        analysis.warnings.extend(warnings)
        return analysis
