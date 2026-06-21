from fastapi import APIRouter, Depends, Response, status

from app.core.dependencies import get_measurement_service, require_any
from app.domain import UserActor
from app.schemas.measurement_schema import MeasurementRequest, MeasurementResponse
from app.services.measurement_service import MeasurementService

router = APIRouter(prefix="/measurements")


@router.post(
    "",
    response_model=MeasurementResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload an anthropometric measurement",
    description=(
        "Idempotent upload of a height/weight measurement for a subject. "
        "Replaying the same id returns the stored record unchanged. "
        "Clinical alerts are generated on first write using WHO standards."
    ),
    responses={
        status.HTTP_200_OK: {
            "description": "Measurement already existed; idempotent replay of the "
            "same id."
        },
        status.HTTP_401_UNAUTHORIZED: {"description": "Missing or invalid token"},
        status.HTTP_403_FORBIDDEN: {"description": "Insufficient permissions"},
        status.HTTP_404_NOT_FOUND: {
            "description": "Subject or establishment not found"
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "description": "Weight, height, or date out of valid range"
        },
    },
)
async def upload_measurement(
    data: MeasurementRequest,
    response: Response,
    actor: UserActor = Depends(require_any),
    service: MeasurementService = Depends(get_measurement_service),
) -> MeasurementResponse:
    measurement, created = await service.register(data, actor)
    if not created:
        response.status_code = status.HTTP_200_OK
    return MeasurementResponse.model_validate(measurement)
