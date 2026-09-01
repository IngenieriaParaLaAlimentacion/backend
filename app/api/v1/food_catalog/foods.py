from fastapi import APIRouter, Depends

from app.api.v1.params import AUTH_RESPONSES, FoodListingQuery, PaginatedQueryParams
from app.core.dependencies import get_food_service, require_any
from app.domain import UserActor
from app.schemas.food_catalog.food_schema import FoodListItem
from app.schemas.pagination import PaginatedResponse
from app.services.food_catalog.food_service import FoodService

router = APIRouter(prefix="/food-catalog/foods")


@router.get(
    "",
    response_model=PaginatedResponse[FoodListItem],
    summary="List the food catalog",
    description=(
        "Paginated, filterable and sortable list of foods, each with its "
        "category and base unit of measurement. Accessible to any "
        "authenticated role — used to build the stock-logging form. "
        "Inactive foods are excluded unless `is_active=false` is passed."
    ),
    responses=AUTH_RESPONSES,
)
async def list_foods(
    query: FoodListingQuery = Depends(),
    paginated: PaginatedQueryParams = Depends(),
    _: UserActor = Depends(require_any),
    service: FoodService = Depends(get_food_service),
) -> PaginatedResponse[FoodListItem]:
    result = await service.list_foods(
        page=paginated.page, page_size=paginated.page_size, params=query.to_domain()
    )
    return PaginatedResponse[FoodListItem](
        items=[FoodListItem.model_validate(item) for item in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
        total_pages=result.total_pages,
    )
