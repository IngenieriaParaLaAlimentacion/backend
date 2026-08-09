from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.v1.params import (
    AUTH_RESPONSES,
    EstablishmentFieldWorkersQuery,
    EstablishmentListingQuery,
    EstablishmentSubjectsQuery,
    PaginatedQueryParams,
)
from app.core.dependencies import (
    get_establishment_dashboard_service,
    get_establishment_service,
    get_optional_actor,
    require_any,
    require_some,
)
from app.domain import UserActor, UserRole
from app.exceptions.domain_exceptions import ForbiddenError, UnauthorizedError
from app.schemas.establishment_dashboard_schema import (
    EstablishmentDashboardResponse,
    EstablishmentFieldWorkerListItem,
    EstablishmentSubjectListItem,
)
from app.schemas.establishment_schema import (
    EstablishmentCreationRequestCreate,
    EstablishmentCreationRequestResponse,
    EstablishmentRequest,
    EstablishmentResponse,
    EstablishmentUpdateRequest,
)
from app.schemas.pagination import PaginatedResponse
from app.services.establishment_dashboard_service import EstablishmentDashboardService
from app.services.establishment_service import EstablishmentService

router = APIRouter(prefix="/establishments")

_FIELD_WORKER_ROLES = {
    UserRole.FIELD_WORKER,
    UserRole.SUPERADMIN,
}  # TODO: review, not sure if its necessary

require_admin_or_analyst = require_some(
    UserRole.ADMIN, UserRole.ANALYST, UserRole.SUPERADMIN
)


@router.post(
    "",
    response_model=EstablishmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new establishment",
    description="Creates a new establishment.",
    responses={
        status.HTTP_400_BAD_REQUEST: {"description": "Invalid data"},
        **AUTH_RESPONSES,
        status.HTTP_409_CONFLICT: {"description": "Establishment already exists"},
    },
)
async def create_establishment(
    data: EstablishmentRequest,
    _: UserActor = Depends(require_some(UserRole.ADMIN, UserRole.SUPERADMIN)),
    service: EstablishmentService = Depends(get_establishment_service),
) -> EstablishmentResponse:
    """Register a new establishment."""
    establishment = await service.create_establishment(data)
    return EstablishmentResponse.model_validate(establishment)


@router.post(
    "/requests",
    response_model=EstablishmentCreationRequestResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Request creation of a missing establishment",
    description="Notifies an admin that the establishment the field worker "
    "needs access to is missing from the catalog, so it can be reviewed and "
    "registered. All fields are optional: the field worker provides as much "
    "as they know, possibly nothing.",
    responses={
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"description": "Invalid data"},
        **AUTH_RESPONSES,
    },
)
async def create_establishment_request(
    data: EstablishmentCreationRequestCreate,
    actor: UserActor = Depends(
        require_some(UserRole.FIELD_WORKER, UserRole.SUPERADMIN)
        # TODO: take into a new variable if it does not already exits, do not remember
    ),
    service: EstablishmentService = Depends(get_establishment_service),
) -> EstablishmentCreationRequestResponse:
    """Register a notification requesting the creation of a missing establishment."""
    request = await service.create_establishment_request(actor.user_id, data)
    return EstablishmentCreationRequestResponse.model_validate(request)


@router.patch(
    "/{establishment_id}",
    response_model=EstablishmentResponse,
    status_code=status.HTTP_200_OK,
    summary="Update an establishment",
    description="Partially updates one or more fields of an existing establishment.",
    responses={
        status.HTTP_400_BAD_REQUEST: {"description": "Invalid data"},
        **AUTH_RESPONSES,
        status.HTTP_404_NOT_FOUND: {"description": "Establishment not found"},
        status.HTTP_409_CONFLICT: {"description": "Establishment already exists"},
    },
)
async def update_establishment(
    establishment_id: UUID,
    data: EstablishmentUpdateRequest,
    _: UserActor = Depends(require_some(UserRole.ADMIN, UserRole.SUPERADMIN)),
    service: EstablishmentService = Depends(get_establishment_service),
) -> EstablishmentResponse:
    """Partially update an establishment."""
    establishment = await service.update_establishment(establishment_id, data)
    return EstablishmentResponse.model_validate(establishment)


@router.get(
    "",
    response_model=PaginatedResponse[EstablishmentResponse],
    status_code=status.HTTP_200_OK,
    summary="List all establishments",
    description="Public catalog of establishments. Supports optional search "
    "filtering by establishment name or address. When 'available' is set, requires "
    "a field worker token and returns only establishments that field worker "
    "can still request (excludes approved/pending relations).",
    responses={
        status.HTTP_400_BAD_REQUEST: {"description": "Invalid query parameters"},
        status.HTTP_401_UNAUTHORIZED: {
            "description": "Missing or invalid token (only when 'available' is set)"
        },
        status.HTTP_403_FORBIDDEN: {
            "description": "Caller is not a field worker (only when 'available' is set)"
        },
    },
)
async def get_establishments(
    paginated: PaginatedQueryParams = Depends(),
    query: EstablishmentListingQuery = Depends(),
    available: bool = Query(
        default=False,
        description="If true, return only establishments the authenticated "
        "field worker can still request (excludes approved/pending). "
        "Field worker only.",
    ),
    actor: UserActor | None = Depends(get_optional_actor),
    service: EstablishmentService = Depends(get_establishment_service),
) -> PaginatedResponse[EstablishmentResponse]:
    params = query.to_domain()
    if available:
        if actor is None:
            raise UnauthorizedError()
        if actor.role not in _FIELD_WORKER_ROLES:
            raise ForbiddenError()
        result = await service.get_available_establishments(
            user_id=actor.user_id,
            page=paginated.page,
            page_size=paginated.page_size,
            params=params,
        )
    else:
        result = await service.get_establishments_paginated(
            page=paginated.page, page_size=paginated.page_size, params=params
        )

    return PaginatedResponse[EstablishmentResponse](
        items=[EstablishmentResponse.model_validate(estab) for estab in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
        total_pages=result.total_pages,
    )


@router.get(
    "/{establishment_id}",
    response_model=EstablishmentResponse,
    status_code=status.HTTP_200_OK,
    summary="Get an establishment by ID",
    description="Returns the details of a single establishment.",
    responses={
        status.HTTP_400_BAD_REQUEST: {"description": "Invalid establishment ID"},
        **AUTH_RESPONSES,
        status.HTTP_404_NOT_FOUND: {"description": "Establishment not found"},
    },
)
async def get_establishment_detail(
    establishment_id: UUID,
    _: UserActor = Depends(require_any),
    service: EstablishmentService = Depends(get_establishment_service),
) -> EstablishmentResponse:
    establishment = await service.get_establishment_by_id(establishment_id)
    return EstablishmentResponse.model_validate(establishment)


# Dashboard Endpoints


@router.get(
    "/{establishment_id}/dashboard",
    response_model=EstablishmentDashboardResponse,
    status_code=status.HTTP_200_OK,
    summary="Get aggregated metrics and alert status for an establishment",
    description=(
        "Returns the establishment's identification data, aggregated metrics "
        "(number of subjects and averages of height, weight, BMI and age) and "
        "its overall alert state. Averages are computed over each subject's most "
        "recent measurement at this establishment. When the establishment has no "
        "measurements, `has_data` is false and every average is null rather than "
        "zero. Accessible by admins and analysts."
    ),
    responses={
        **AUTH_RESPONSES,
        status.HTTP_404_NOT_FOUND: {"description": "Establishment not found"},
    },
)
async def get_establishment_dashboard(
    establishment_id: UUID,
    _: UserActor = Depends(require_admin_or_analyst),
    service: EstablishmentDashboardService = Depends(
        get_establishment_dashboard_service
    ),
) -> EstablishmentDashboardResponse:
    dashboard = await service.get_establishment_dashboard(establishment_id)
    return EstablishmentDashboardResponse.model_validate(dashboard)


@router.get(
    "/{establishment_id}/subjects",
    response_model=PaginatedResponse[EstablishmentSubjectListItem],
    status_code=status.HTTP_200_OK,
    summary="List the subjects attending an establishment",
    description=(
        "Returns a paginated list of the subjects measured at this establishment, "
        "enriched with their latest measurement and derived anthropometric status. "
        "Supports searching by name, last name or DNI, and sorting by measurement "
        "date, name, BMI or age. Accessible by admins and analysts."
    ),
    responses={
        **AUTH_RESPONSES,
        status.HTTP_404_NOT_FOUND: {"description": "Establishment not found"},
    },
)
async def list_establishment_subjects(
    establishment_id: UUID,
    query: EstablishmentSubjectsQuery = Depends(),
    paginated: PaginatedQueryParams = Depends(),
    _: UserActor = Depends(require_admin_or_analyst),
    service: EstablishmentDashboardService = Depends(
        get_establishment_dashboard_service
    ),
) -> PaginatedResponse[EstablishmentSubjectListItem]:
    result = await service.list_establishment_subjects(
        establishment_id=establishment_id,
        page=paginated.page,
        page_size=paginated.page_size,
        params=query.to_domain(),
    )
    return PaginatedResponse[EstablishmentSubjectListItem](
        items=[EstablishmentSubjectListItem.model_validate(i) for i in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
        total_pages=result.total_pages,
    )


@router.get(
    "/{establishment_id}/field-workers",
    response_model=PaginatedResponse[EstablishmentFieldWorkerListItem],
    status_code=status.HTTP_200_OK,
    summary="List the field workers enrolled at an establishment",
    description=(
        "Returns a paginated list of the users enrolled in this establishment "
        "together with how many measurements each has taken here and when they "
        "last did. Defaults to approved enrollments; use `relation_status` to see "
        "pending or rejected ones. Accessible by admins and analysts."
    ),
    responses={
        **AUTH_RESPONSES,
        status.HTTP_404_NOT_FOUND: {"description": "Establishment not found"},
    },
)
async def list_establishment_field_workers(
    establishment_id: UUID,
    query: EstablishmentFieldWorkersQuery = Depends(),
    paginated: PaginatedQueryParams = Depends(),
    _: UserActor = Depends(require_admin_or_analyst),
    service: EstablishmentDashboardService = Depends(
        get_establishment_dashboard_service
    ),
) -> PaginatedResponse[EstablishmentFieldWorkerListItem]:
    result = await service.list_establishment_field_workers(
        establishment_id=establishment_id,
        page=paginated.page,
        page_size=paginated.page_size,
        params=query.to_domain(),
    )
    return PaginatedResponse[EstablishmentFieldWorkerListItem](
        items=[
            EstablishmentFieldWorkerListItem.model_validate(i) for i in result.items
        ],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
        total_pages=result.total_pages,
    )
