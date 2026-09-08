from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile, status

from app.api.v1.params import AUTH_RESPONSES
from app.core.dependencies import (
    get_food_intake_service,
    get_receipt_intake_service,
    require_any,
)
from app.domain import UserActor
from app.schemas.food_intakes.food_intake_schema import (
    FoodIntakeRequest,
    FoodIntakeResponse,
)
from app.schemas.food_intakes.receipt_schema import ReceiptProposalResponse
from app.services.food_intakes.food_intake_service import FoodIntakeService
from app.services.food_intakes.receipt_intake_service import ReceiptIntakeService

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


@router.post(
    "/from-photo",
    response_model=ReceiptProposalResponse,
    summary="Propose food lines from a photo of the receipt",
    description=(
        "Accepts a `multipart/form-data` upload with the receipt `image` and the "
        "`establishment_id` it belongs to. The image is validated (type and "
        "size) and a proposal of detected food lines is returned for the user to "
        "review and correct. Nothing is stored — the confirmed lines are then "
        "submitted through `POST /food-intakes` with `source=photo`.\n\n"
        "Unsupported image types and oversized files are rejected with `422`."
    ),
    responses={
        **AUTH_RESPONSES,
        status.HTTP_404_NOT_FOUND: {"description": "Establishment not found"},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "description": "Unsupported image type, or file over the size limit"
        },
    },
)
async def propose_food_intake_from_photo(
    establishment_id: UUID = Form(
        ..., description="Establishment the receipt belongs to."
    ),
    image: UploadFile = File(..., description="Receipt image (jpeg, png or webp)."),
    actor: UserActor = Depends(require_any),
    service: ReceiptIntakeService = Depends(get_receipt_intake_service),
) -> ReceiptProposalResponse:
    return await service.propose_from_photo(
        establishment_id=establishment_id,
        content_type=image.content_type,
        image=await image.read(),
        actor=actor,
    )
