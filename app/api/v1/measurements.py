from fastapi import APIRouter, Depends, Response, status
from fastapi.responses import StreamingResponse

from app.api.v1.exports import CSV_EXPORT_RESPONSES, csv_stream_response
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
from app.services.exporters.csv.columns import MEASUREMENT_LISTING_EXPORTER
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


@router.get(
    "/export",
    summary="Export the measurement listing as CSV",
    description=(
        "Download the anthropometric measurement listing as a CSV file. "
        "Accepts the same filters and sort order as the listing endpoint and "
        "exports every matching measurement rather than one page, so the file "
        "mirrors what the user has on screen. A filter matching nothing still "
        "returns a valid file carrying only the column headers. Restricted to "
        "admins, analysts and superadmins."
    ),
    responses={
        **CSV_EXPORT_RESPONSES,
        status.HTTP_400_BAD_REQUEST: {
            "description": "Invalid filter range, or a value with no export label"
        },
    },
)
async def export_measurements(
    query: MeasurementListingQuery = Depends(),
    _: UserActor = Depends(require_admin_or_analyst),
    service: MeasurementService = Depends(get_measurement_service),
) -> StreamingResponse:
    query.validate()
    params = query.to_domain()
    total = await service.count_measurement_export(params)
    return csv_stream_response(
        lambda uow: MeasurementService(uow).export_measurement_listing(
            params, MEASUREMENT_LISTING_EXPORTER
        ),
        MEASUREMENT_LISTING_EXPORTER.filename(),
        total,
    )
