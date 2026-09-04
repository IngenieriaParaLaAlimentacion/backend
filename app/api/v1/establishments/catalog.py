from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import StreamingResponse

from app.api.v1.exports import CSV_EXPORT_RESPONSES, csv_stream_response
from app.api.v1.params import (
    AUTH_RESPONSES,
    EstablishmentListingQuery,
    PaginatedQueryParams,
)
from app.core.dependencies import (
    get_establishment_service,
    get_optional_actor,
    require_admin,
    require_admin_or_analyst,
    require_any,
)
from app.domain import UserActor
from app.exceptions.domain_exceptions import MissingTokenError
from app.schemas.establishments.establishment_schema import (
    EstablishmentCreationRequestCreate,
    EstablishmentCreationRequestResponse,
    EstablishmentRequest,
    EstablishmentResponse,
    EstablishmentUpdateRequest,
)
from app.schemas.pagination import PaginatedResponse
from app.services.establishments.establishment_service import EstablishmentService
from app.services.exporters.csv.columns import ESTABLISHMENT_LISTING_EXPORTER

router = APIRouter(prefix="/establishments")


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
    _: UserActor = Depends(require_admin),
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
    "registered. Name and address are not optional.",
    responses={
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"description": "Invalid data"},
        **AUTH_RESPONSES,
    },
)
async def create_establishment_request(
    data: EstablishmentCreationRequestCreate,
    actor: UserActor = Depends(require_any),
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
    _: UserActor = Depends(require_admin),
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
    "any authenticated token and returns only establishments that caller can "
    "still request (excludes approved/pending relations).",
    responses={
        status.HTTP_400_BAD_REQUEST: {"description": "Invalid query parameters"},
        status.HTTP_401_UNAUTHORIZED: {
            "description": "Missing or invalid token (only when 'available' is set)"
        },
    },
)
async def get_establishments(
    paginated: PaginatedQueryParams = Depends(),
    query: EstablishmentListingQuery = Depends(),
    available: bool = Query(
        default=False,
        description="If true, return only establishments the authenticated "
        "caller can still request (excludes approved/pending). "
        "Requires a token.",
    ),
    actor: UserActor | None = Depends(get_optional_actor),
    service: EstablishmentService = Depends(get_establishment_service),
) -> PaginatedResponse[EstablishmentResponse]:
    params = query.to_domain()
    if available:
        if actor is None:
            raise MissingTokenError()
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


# Declared above GET /{establishment_id} so "export" is not matched as an id.
@router.get(
    "/export",
    summary="Export the establishment listing as CSV",
    description=(
        "Download the establishment listing as a CSV file. Accepts the same "
        "search, city, province and sort order as the listing endpoint and "
        "exports every match rather than one page, so the file mirrors what "
        "the user has on screen. A filter matching nothing still returns a "
        "valid file carrying only the column headers. Unlike the listing, "
        "which is public, exporting the whole catalogue is restricted to "
        "admins, analysts and superadmins."
    ),
    responses=CSV_EXPORT_RESPONSES,
)
async def export_establishments(
    query: EstablishmentListingQuery = Depends(),
    _: UserActor = Depends(require_admin_or_analyst),
    service: EstablishmentService = Depends(get_establishment_service),
) -> StreamingResponse:
    params = query.to_domain()
    total = await service.count_establishment_export(params)
    return csv_stream_response(
        lambda uow: EstablishmentService(uow).export_establishment_listing(
            params, ESTABLISHMENT_LISTING_EXPORTER
        ),
        ESTABLISHMENT_LISTING_EXPORTER.filename(),
        total,
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
