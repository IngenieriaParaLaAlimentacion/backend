from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi.responses import StreamingResponse

from app.api.v1.exports import CSV_EXPORT_RESPONSES, csv_stream_response
from app.api.v1.params import AUTH_RESPONSES, PaginatedQueryParams, SubjectListingQuery
from app.core.dependencies import (
    get_measurement_service,
    get_subject_service,
    require_admin_or_analyst,
    require_any,
)
from app.domain import UserActor
from app.domain.measurement import EvolutionOrder
from app.schemas.measurements.measurement_schema import SubjectEvolutionResponse
from app.schemas.pagination import PaginatedResponse
from app.schemas.subjects.subject_schema import (
    SubjectDetailResponse,
    SubjectListingResponse,
    SubjectRequest,
    SubjectResponse,
    SubjectUpdateRequest,
)
from app.services.exporters.csv.columns import SUBJECT_LISTING_EXPORTER
from app.services.measurements.measurement_service import MeasurementService
from app.services.subjects.subject_service import SubjectService

router = APIRouter(prefix="/subjects")


@router.post(
    "",
    response_model=SubjectResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new subject",
    description="Creates a new subject. Accessible by field workers only.",
    responses={
        status.HTTP_200_OK: {
            "description": "Subject already existed; idempotent replay of the same id."
        },
        status.HTTP_400_BAD_REQUEST: {"description": "Invalid data"},
        **AUTH_RESPONSES,
        status.HTTP_409_CONFLICT: {
            "description": "A subject with this DNI already exists under a different "
            "id; the canonical subject is returned in `canonical_subject`."
        },
    },
)
async def create_subject(
    data: SubjectRequest,
    response: Response,
    user: UserActor = Depends(require_any),
    service: SubjectService = Depends(get_subject_service),
) -> SubjectResponse:
    """Register a new subject (idempotent on the client-supplied id)."""
    subject, created = await service.create_subject(data, actor_id=user.user_id)
    if not created:
        response.status_code = status.HTTP_200_OK
    return SubjectResponse.model_validate(subject)


# Declared above GET /{subject_id} so "export" is not matched as a subject id.
@router.get(
    "/export",
    summary="Export the subject listing as CSV",
    description=(
        "Download the subject listing as a CSV file. Accepts the same filters "
        "and sort order as the listing endpoint and exports every matching "
        "subject rather than one page, so the file mirrors what the user has "
        "on screen. A filter matching nothing still returns a valid file "
        "carrying only the column headers. Restricted to admins, analysts and "
        "superadmins."
    ),
    responses={
        **CSV_EXPORT_RESPONSES,
        status.HTTP_400_BAD_REQUEST: {
            "description": "Invalid filter range, or a value with no export label"
        },
    },
)
async def export_subjects(
    query: SubjectListingQuery = Depends(),
    _: UserActor = Depends(require_admin_or_analyst),
    service: SubjectService = Depends(get_subject_service),
) -> StreamingResponse:
    query.validate()
    params = query.to_domain()
    total = await service.count_subject_export(params)
    return csv_stream_response(
        lambda uow: SubjectService(uow).export_subject_listing(
            params, SUBJECT_LISTING_EXPORTER
        ),
        SUBJECT_LISTING_EXPORTER.filename(),
        total,
    )


@router.get(
    "/{subject_id}",
    response_model=SubjectDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a subject by ID",
    description=(
        "Returns a subject's data together with their latest measurement across "
        "every establishment and the anthropometric status derived from it. Both "
        "are null when the subject has never been measured, which is distinct "
        "from a `normal` status. Accessible by all authenticated roles."
    ),
    responses={
        **AUTH_RESPONSES,
        status.HTTP_404_NOT_FOUND: {"description": "Subject not found"},
    },
)
async def get_subject(
    subject_id: UUID,
    _: UserActor = Depends(require_any),
    service: SubjectService = Depends(get_subject_service),
) -> SubjectDetailResponse:
    """Return a subject by id, enriched with their latest measurement."""
    subject = await service.get_subject(subject_id)
    return SubjectDetailResponse.model_validate(subject)


@router.get(
    "",
    response_model=PaginatedResponse[SubjectListingResponse],
    status_code=status.HTTP_200_OK,
    summary="List subjects",
    description=(
        "Returns a paginated list of subjects. Supports search by name, last "
        "name or DNI; filtering by birth date range, establishment, rurality, "
        "indigenous status and sex; and sorting by name, creation date or "
        "birth date in either direction. Accessible by all authenticated roles."
    ),
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "description": "`/errors/invalid-date-range`: birth_date_from is after "
            "birth_date_to"
        },
        **AUTH_RESPONSES,
    },
)
async def list_subjects(
    paginated: PaginatedQueryParams = Depends(),
    query: SubjectListingQuery = Depends(),
    _: UserActor = Depends(require_any),
    service: SubjectService = Depends(get_subject_service),
) -> PaginatedResponse[SubjectListingResponse]:
    query.validate()
    result = await service.get_subject_listing(
        page=paginated.page, page_size=paginated.page_size, params=query.to_domain()
    )

    return PaginatedResponse[SubjectListingResponse](
        items=[
            SubjectListingResponse.model_validate(subject) for subject in result.items
        ],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
        total_pages=result.total_pages,
    )


@router.get(
    "/{subject_id}/measurements/evolution",
    response_model=SubjectEvolutionResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a subject's anthropometric evolution",
    description=(
        "Returns the subject's full weight, height and BMI series for trend "
        "charting, ordered by measurement date. Use the `order` parameter to "
        "choose oldest-first (default) or newest-first. Accessible by admins "
        "and analysts."
    ),
    responses={
        **AUTH_RESPONSES,
        status.HTTP_404_NOT_FOUND: {"description": "Subject not found"},
    },
)
async def get_subject_evolution(
    subject_id: UUID,
    order: EvolutionOrder = Query(
        default=EvolutionOrder.OLDEST_FIRST,
        description="Chronological order of the returned series.",
    ),
    _: UserActor = Depends(require_admin_or_analyst),
    service: MeasurementService = Depends(get_measurement_service),
) -> SubjectEvolutionResponse:
    evolution = await service.get_subject_evolution(subject_id, order=order)
    return SubjectEvolutionResponse.model_validate(evolution)


@router.patch(
    "/{subject_id}",
    response_model=SubjectResponse,
    status_code=status.HTTP_200_OK,
    summary="Update a subject",
    description="Partially updates a subject's data. Accessible by field workers only.",
    responses={
        status.HTTP_400_BAD_REQUEST: {"description": "No fields provided"},
        **AUTH_RESPONSES,
        status.HTTP_404_NOT_FOUND: {"description": "Subject not found"},
        status.HTTP_409_CONFLICT: {
            "description": "DNI already belongs to another subject"
        },
    },
)
async def update_subject(
    subject_id: UUID,
    data: SubjectUpdateRequest,
    user: UserActor = Depends(require_any),
    service: SubjectService = Depends(get_subject_service),
) -> SubjectResponse:
    subject = await service.update_subject(subject_id, data, actor_id=user.user_id)
    return SubjectResponse.model_validate(subject)
