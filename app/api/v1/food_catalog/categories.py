from fastapi import APIRouter, Depends

from app.api.v1.params import AUTH_RESPONSES, FoodCategoryListingQuery
from app.core.dependencies import get_food_category_service, require_any
from app.domain import UserActor
from app.schemas.food_catalog.food_schema import FoodCategoryRefResponse
from app.services.food_catalog.food_category_service import FoodCategoryService

router = APIRouter(prefix="/food-catalog/categories")


@router.get(
    "",
    response_model=list[FoodCategoryRefResponse],
    summary="List food categories",
    description=(
        "Every food category (the ~26 SARA 2 food groups). Not paginated — "
        "the table is structurally bounded. Sorted alphabetically by name "
        "(`name_asc`) by default; pass `sort_order` to change it. Accessible "
        "to any authenticated role."
    ),
    responses=AUTH_RESPONSES,
)
async def list_categories(
    query: FoodCategoryListingQuery = Depends(),
    _: UserActor = Depends(require_any),
    service: FoodCategoryService = Depends(get_food_category_service),
) -> list[FoodCategoryRefResponse]:
    categories = await service.list_categories(query.to_domain())
    return [FoodCategoryRefResponse.model_validate(c) for c in categories]
