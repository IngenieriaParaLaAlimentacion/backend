from fastapi import APIRouter, Depends, Response, status

from app.api.v1.params import AUTH_RESPONSES
from app.core.dependencies import get_food_intake_service, require_any
from app.domain import UserActor
from app.schemas.food_intakes.food_intake_schema import (
    FoodIntakeRequest,
    FoodIntakeResponse,
)
from app.services.food_intakes.food_intake_service import FoodIntakeService

router = APIRouter(prefix="/food-intakes")


@router.post(
    "",
    response_model=FoodIntakeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register food received by an establishment",
    description=(
        "Records a delivery and adds every line to the establishment's stock, in "
        "one transaction. Send a client-generated `id` to make the submission "
        "idempotent: a replay of an id that already exists answers 200 and leaves "
        "the stock untouched, so a retried offline sync cannot inflate it.\n\n"
        "Each line's unit is not sent — it is the referenced catalog food's "
        "`base_unit`."
    ),
    responses={
        status.HTTP_200_OK: {
            "description": "Intake already existed; idempotent replay of the same id."
        },
        **AUTH_RESPONSES,
        status.HTTP_404_NOT_FOUND: {"description": "Establishment or food not found"},
    },
)
async def register_food_intake(
    data: FoodIntakeRequest,
    response: Response,
    actor: UserActor = Depends(require_any),
    service: FoodIntakeService = Depends(get_food_intake_service),
) -> FoodIntakeResponse:
    intake, created = await service.register(data, actor)
    if not created:
        response.status_code = status.HTTP_200_OK
    return FoodIntakeResponse.model_validate(intake)
