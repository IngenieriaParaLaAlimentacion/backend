from uuid import UUID

from app.core.interfaces.unit_of_work import IUnitOfWork
from app.domain.food_catalog import (
    FoodDetailDomain,
    FoodListingParams,
    FoodListItemDomain,
)
from app.domain.pagination import PaginatedResult
from app.exceptions.domain_exceptions import FoodNotFoundError


class FoodService:
    """Business logic for reading the food catalog."""

    def __init__(self, uow: IUnitOfWork) -> None:
        self.uow = uow

    async def get_food(self, food_id: UUID) -> FoodDetailDomain:
        """Return a food's full detail, including its nutrient composition.

        Raises:
            FoodNotFoundError: If no food with that id exists.
        """
        food = await self.uow.food_repo.get_by_id(food_id)
        if food is None:
            raise FoodNotFoundError(str(food_id))
        return FoodDetailDomain.from_db(food)

    async def list_foods(
        self,
        page: int,
        page_size: int,
        params: FoodListingParams,
    ) -> PaginatedResult[FoodListItemDomain]:
        """Return a paginated, filtered and sorted list of foods."""
        page = max(1, page)
        offset = (page - 1) * page_size
        foods, total = await self.uow.food_repo.list(
            limit=page_size, offset=offset, params=params
        )
        return PaginatedResult.build(
            items=[FoodListItemDomain.from_db(food) for food in foods],
            total=total,
            page=page,
            page_size=page_size,
        )
