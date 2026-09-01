from fastapi import APIRouter, Depends, Response, status

from app.api.v1.params import (
    AUTH_RESPONSES,
    MeasurementListingQuery,
    PaginatedQueryParams,
)
from app.core.dependencies import (
    get_measurement_service,
    require_admin_or_analyst,
    require_any,
)
from app.domain import UserActor
from app.schemas.measurements.measurement_schema import (
    MeasurementListItem,
    MeasurementRequest,
    MeasurementResponse,
)
from app.schemas.pagination import PaginatedResponse
from app.services.measurements.measurement_service import MeasurementService

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
        **AUTH_RESPONSES,
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


@router.get(
    "",
    response_model=PaginatedResponse[MeasurementListItem],
    status_code=status.HTTP_200_OK,
    summary="List anthropometric measurements",
    description=(
        "Returns a paginated list of measurements enriched with subject, "
        "establishment and responsible data. Supports filtering by subject, "
        "establishment, city, province, responsible, measurement-date range and "
        "subject age, plus sorting. Accessible by admins and analysts."
    ),
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "description": "`/errors/invalid-date-range`: measured_from is after "
            "measured_to. `/errors/invalid-age-range`: min_age is above max_age."
        },
        **AUTH_RESPONSES,
    },
)
async def list_measurements(
    query: MeasurementListingQuery = Depends(),
    paginated: PaginatedQueryParams = Depends(),
    _: UserActor = Depends(require_admin_or_analyst),
    service: MeasurementService = Depends(get_measurement_service),
) -> PaginatedResponse[MeasurementListItem]:
    query.validate()
    result = await service.list_measurements(
        page=paginated.page, page_size=paginated.page_size, params=query.to_domain()
    )
    return PaginatedResponse[MeasurementListItem](
        items=[MeasurementListItem.model_validate(item) for item in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
        total_pages=result.total_pages,
    )
