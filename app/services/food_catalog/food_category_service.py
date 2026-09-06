from app.core.interfaces.unit_of_work import IUnitOfWork
from app.domain.food_catalog import FoodCategoryListingParams
from app.models.food_catalog.food_category import FoodCategory


class FoodCategoryService:
    """Business logic for reading food categories."""

    def __init__(self, uow: IUnitOfWork) -> None:
        self.uow = uow

    async def list_categories(
        self, params: FoodCategoryListingParams
    ) -> list[FoodCategory]:
        """Return every food category, sorted per ``params.sort_order``."""
        return await self.uow.food_category_repo.get_all(params.sort_order)
