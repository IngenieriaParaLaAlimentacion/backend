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
    get_establishment_dashboard_service,
    get_establishment_service,
    get_optional_actor,
    require_admin,
    require_admin_or_analyst,
    require_any,
)
from app.domain import UserActor
from app.exceptions.domain_exceptions import MissingTokenError
from app.exceptions.exception_handlers import INVALID_FIELD_EXTENSION
from app.schemas.establishments.establishment_characterization_schema import (
    EstablishmentCharacterization,
    EstablishmentCharacterizationResponse,
)
from app.schemas.establishments.establishment_dashboard_schema import (
    EstablishmentMapResponse,
)
from app.schemas.establishments.establishment_schema import (
    EstablishmentCreationRequestCreate,
    EstablishmentCreationRequestResponse,
    EstablishmentRequest,
    EstablishmentResponse,
    EstablishmentUpdateRequest,
)
from app.schemas.pagination import PaginatedResponse
from app.services.establishments.establishment_dashboard_service import (
    EstablishmentDashboardService,
)
from app.services.establishments.establishment_service import EstablishmentService
from app.services.exporters.csv.columns import ESTABLISHMENT_LISTING_EXPORTER

router = APIRouter(prefix="/establishments")


@router.post(
    "",
    response_model=EstablishmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new establishment",
    description="Creates a new establishment, optionally with its "
    "characterization profile.",
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "description": "Invalid data; `field` names the field that failed"
        },
        **AUTH_RESPONSES,
        status.HTTP_409_CONFLICT: {"description": "Establishment already exists"},
    },
    openapi_extra={INVALID_FIELD_EXTENSION: True},
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
    description="Notifies an admin that the establishment the authenticated user "
    "needs access to is missing from the catalog, so it can be reviewed and "
    "registered. Name and address are not optional; a characterization "
    "profile may be proposed with it.",
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "description": "Invalid data; `field` names the field that failed"
        },
        **AUTH_RESPONSES,
    },
    openapi_extra={INVALID_FIELD_EXTENSION: True},
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


@router.put(
    "/{establishment_id}/characterization",
    response_model=EstablishmentCharacterizationResponse,
    status_code=status.HTTP_200_OK,
    summary="Replace an establishment's characterization profile",
    description=(
        "Replaces the whole profile: a field sent as `null` or `[]`, or left "
        "out, clears what was stored. `characterization_status` is computed "
        "and ignored if sent. Each `*_other` text is accepted only when "
        '`"other"` is chosen in its field. A 422 carries a `field` extension '
        "naming the body field that failed (`opening_hours` for any error "
        "inside a slot). Accessible by admins, superadmins and field workers "
        "with approved access to this establishment."
    ),
    responses={
        **AUTH_RESPONSES,
        status.HTTP_404_NOT_FOUND: {"description": "Establishment not found"},
        status.HTTP_400_BAD_REQUEST: {
            "description": "Invalid profile; `field` names the field that failed"
        },
    },
    openapi_extra={INVALID_FIELD_EXTENSION: True},
)
async def replace_establishment_characterization(
    establishment_id: UUID,
    data: EstablishmentCharacterization,
    actor: UserActor = Depends(require_any),
    service: EstablishmentService = Depends(get_establishment_service),
) -> EstablishmentCharacterizationResponse:
    establishment = await service.replace_characterization(
        establishment_id, actor, data
    )
    return EstablishmentCharacterizationResponse.model_validate(establishment)


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


# "/map" and "/export" are declared above GET /{establishment_id} so they are
# not matched as an id.
@router.get(
    "/map",
    response_model=EstablishmentMapResponse,
    status_code=status.HTTP_200_OK,
    summary="Get every establishment's location and nutritional status for the map",
    description=(
        "Returns, in a single unpaginated response, the location and "
        "rolled-up nutritional severity of every establishment. "
        "An establishment with no measurements is returned with "
        "has_data=false rather than omitted. Restricted to admins and "
        "analysts."
    ),
    responses=AUTH_RESPONSES,
)
async def get_establishments_map(
    _: UserActor = Depends(require_admin_or_analyst),
    service: EstablishmentDashboardService = Depends(
        get_establishment_dashboard_service
    ),
) -> EstablishmentMapResponse:
    items = await service.get_establishments_map()
    return EstablishmentMapResponse.model_validate({"establishments": items})


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
