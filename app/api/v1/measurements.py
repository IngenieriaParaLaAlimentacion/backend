from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.core.dependencies import get_measurement_service, require_any
from app.domain import UserActor
from app.schemas.measurement_schema import MeasurementRequest, MeasurementResponse
from app.services.measurement_service import MeasurementService

router = APIRouter(prefix="/measurements")


@router.put(
    "/{idempotency_key}",
    response_model=MeasurementResponse,
    status_code=status.HTTP_200_OK,
    summary="Upload an anthropometric measurement",
    description=(
        "Idempotent upload of a height/weight measurement for a subject. "
        "Replaying the same idempotency_key returns the stored record unchanged. "
        "Clinical alerts are generated on first write using WHO standards."
    ),
    responses={
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
    idempotency_key: UUID,
    data: MeasurementRequest,
    actor: UserActor = Depends(require_any),
    service: MeasurementService = Depends(get_measurement_service),
) -> MeasurementResponse:
    measurement = await service.register(idempotency_key, data, actor)
    return MeasurementResponse.model_validate(measurement)
