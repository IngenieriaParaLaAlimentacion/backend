from app.core.interfaces.unit_of_work import IUnitOfWork
from app.models.food_catalog.food_category import FoodCategory


class FoodCategoryService:
    """Business logic for reading food categories."""

    def __init__(self, uow: IUnitOfWork) -> None:
        self.uow = uow

    async def list_categories(self) -> list[FoodCategory]:
        """Return every food category, in SARA 2 source order."""
        return await self.uow.food_category_repo.get_all()
