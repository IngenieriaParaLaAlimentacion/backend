from fastapi import APIRouter, Depends, Response, status

from app.api.v1.params import AUTH_RESPONSES
from app.core.dependencies import get_food_outflow_service, require_any
from app.domain import UserActor
from app.schemas.food_outflows.food_outflow_schema import (
    FoodOutflowRequest,
    FoodOutflowResponse,
)
from app.services.food_outflows.food_outflow_service import FoodOutflowService

router = APIRouter(prefix="/food-outflows")


@router.post(
    "",
    response_model=FoodOutflowResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register food taken out of an establishment's stock",
    description=(
        "Records an outflow and subtracts every line from the establishment's "
        "stock, in one transaction. A line the balance cannot cover answers 409 "
        "and nothing is persisted — a partially applied outflow is never left "
        "behind.\n\n"
        "Send a client-generated `id` to make the submission idempotent: a replay "
        "answers 200 and leaves the stock untouched.\n\n"
        "`category` is family_delivery, kitchen, discard, or other. `comments` "
        "may be supplied only with other; omit the key for all other values. "
        "Omitting category temporarily records other for older clients."
    ),
    responses={
        status.HTTP_200_OK: {
            "description": "Outflow already existed; idempotent replay of the same id."
        },
        **AUTH_RESPONSES,
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "description": (
                "Invalid category or comments supplied for a non-other category"
            )
        },
        status.HTTP_404_NOT_FOUND: {"description": "Establishment or food not found"},
        status.HTTP_409_CONFLICT: {
            "description": "A line exceeds the food's current stock"
        },
    },
)
async def register_food_outflow(
    data: FoodOutflowRequest,
    response: Response,
    actor: UserActor = Depends(require_any),
    service: FoodOutflowService = Depends(get_food_outflow_service),
) -> FoodOutflowResponse:
    outflow, created = await service.register(data, actor)
    if not created:
        response.status_code = status.HTTP_200_OK
    return FoodOutflowResponse.model_validate(outflow)
