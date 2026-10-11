from uuid import UUID

from app.core.interfaces.unit_of_work import IUnitOfWork
from app.domain.nutrition import (
    FoodQuantity,
    MonthlyIntakeAnalysis,
    NutritionIndicators,
    RecipeRequest,
    RecipeSolution,
)
from app.domain.user import UserActor
from app.services.nutrition.grams import GramsConverter


class NutritionService:
    """Nutritional balance of food combinations, recipes and monthly intakes."""

    def __init__(self, uow: IUnitOfWork, grams: GramsConverter) -> None:
        self.uow = uow
        self.grams = grams

    async def calculate_indicators(
        self, items: list[FoodQuantity]
    ) -> NutritionIndicators:
        """Return the balance indicators of a list of foods in grams."""
        raise NotImplementedError

    async def maximize_recipe(
        self, establishment_id: UUID, request: RecipeRequest, actor: UserActor
    ) -> RecipeSolution:
        """Return the quantities that make the most balanced recipe the stock allows.

        Raises:
            EstablishmentNotFoundError: establishment_id does not exist.
            EstablishmentAccessDeniedError: field worker lacks approved access.
        """
        raise NotImplementedError

    async def analyze_monthly_intake(
        self, establishment_id: UUID, year: int, month: int, actor: UserActor
    ) -> MonthlyIntakeAnalysis:
        """Return the balance of everything the establishment received in a month.

        Raises:
            EstablishmentNotFoundError: establishment_id does not exist.
            EstablishmentAccessDeniedError: field worker lacks approved access.
        """
        raise NotImplementedError
