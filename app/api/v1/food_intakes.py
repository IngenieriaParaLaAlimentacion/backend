from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile, status
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

from app.api.v1.params import AUTH_RESPONSES
from app.core.dependencies import (
    get_food_intake_service,
    get_receipt_intake_service,
    require_any,
)
from app.core.rate_limit import limit_by_user
from app.domain import UserActor
from app.schemas.food_intakes.food_intake_schema import (
    FoodIntakeRequest,
    FoodIntakeResponse,
)
from app.schemas.food_intakes.receipt_schema import ReceiptProposalResponse
from app.services.food_intakes.food_intake_service import FoodIntakeService
from app.services.food_intakes.receipt_intake_service import ReceiptIntakeService

router = APIRouter(prefix="/food-intakes")


def _parse_intake_data(data: str = Form(...)) -> FoodIntakeRequest:
    """Parse the JSON-encoded intake payload carried alongside a photo upload.

    Multipart requests can't nest a structured `items` array in a plain Form
    field, so the client sends the same shape ``POST /food-intakes`` takes,
    JSON-encoded, in one `data` field next to the file. A malformed payload is
    re-raised as ``RequestValidationError`` so it renders through the same
    canonical 422 envelope as any other invalid request body, rather than the
    plain ``pydantic.ValidationError`` the framework wouldn't otherwise catch.
    """
    try:
        return FoodIntakeRequest.model_validate_json(data)
    except ValidationError as exc:
        raise RequestValidationError(exc.errors()) from exc


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
        "`origin_type` (one of the documented food sources) and boolean "
        "`is_recurring` are required for manual and photo-confirmed intakes. "
        "`source` only identifies manual versus photo capture. "
        "Each line's unit is not sent — it is the referenced catalog food's "
        "`base_unit`."
    ),
    responses={
        status.HTTP_200_OK: {
            "description": "Intake already existed; idempotent replay of the same id."
        },
        **AUTH_RESPONSES,
        status.HTTP_404_NOT_FOUND: {"description": "Establishment or food not found"},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "description": "Invalid intake data, including missing or invalid "
            "origin_type or is_recurring"
        },
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
    dependencies=[limit_by_user("rate_limit_ai_user", "ai")],
    response_model=ReceiptProposalResponse,
    summary="Propose food lines from a photo of the receipt",
    description=(
        "Accepts a `multipart/form-data` upload with the receipt `image` and the "
        "`establishment_id` it belongs to. The image is validated (type and "
        "size) and a proposal of detected food lines is returned for the user to "
        "review and correct. Nothing is stored here — the reviewed lines and the "
        "same image are then submitted to "
        "`POST /food-intakes/from-photo/confirm`.\n\n"
        "Unsupported image types and oversized files are rejected with `422`."
    ),
    responses={
        **AUTH_RESPONSES,
        429: {"description": "Caller rate limit exceeded; retry after Retry-After"},
        status.HTTP_404_NOT_FOUND: {"description": "Establishment not found"},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "description": "Unsupported image type, file over the size limit, "
            "or file content does not match the declared type"
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


@router.post(
    "/from-photo/confirm",
    response_model=FoodIntakeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Confirm a food intake reviewed from a receipt photo",
    description=(
        "Uploads the receipt image again alongside the reviewed intake data "
        "(the same shape `POST /food-intakes` takes, including required "
        "`origin_type` and boolean `is_recurring`, JSON-encoded in the `data` field) "
        "and, only if every check passes, saves the photo and registers "
        "the intake in one step. Used both when the photo yielded lines the user "
        "confirmed (`source=photo`) and when it did not and the user fell back to "
        "manual entry but kept the photo (`source=manual`).\n\n"
        "The image is re-sent rather than referenced by a key from the proposal "
        "step: nothing is written to storage until an intake is actually about "
        "to be created, so an abandoned or rejected proposal never leaves an "
        "orphaned photo behind."
    ),
    responses={
        status.HTTP_200_OK: {
            "description": "Intake already existed; idempotent replay of the same id."
        },
        **AUTH_RESPONSES,
        status.HTTP_404_NOT_FOUND: {"description": "Establishment or food not found"},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "description": "Unsupported image type, file over the size limit, "
            "file content does not match the declared type, or invalid `data` "
            "(including missing or invalid origin_type or is_recurring)"
        },
    },
)
async def confirm_food_intake_from_photo(
    response: Response,
    data: FoodIntakeRequest = Depends(_parse_intake_data),
    image: UploadFile = File(..., description="The same receipt image."),
    actor: UserActor = Depends(require_any),
    service: ReceiptIntakeService = Depends(get_receipt_intake_service),
) -> FoodIntakeResponse:
    intake, created = await service.confirm_from_photo(
        data=data,
        content_type=image.content_type,
        image=await image.read(),
        actor=actor,
    )
    if not created:
        response.status_code = status.HTTP_200_OK
    return FoodIntakeResponse.model_validate(intake)
