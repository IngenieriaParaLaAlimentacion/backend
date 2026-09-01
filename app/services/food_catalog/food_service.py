from app.core.interfaces.unit_of_work import IUnitOfWork
from app.domain.food_catalog import FoodListingParams, FoodListItemDomain
from app.domain.pagination import PaginatedResult


class FoodService:
    """Business logic for reading the food catalog."""

    def __init__(self, uow: IUnitOfWork) -> None:
        self.uow = uow

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
