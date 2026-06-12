from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.core.dependencies import get_establishment_service, require_any, require_some
from app.domain import UserActor, UserRole
from app.domain.establishment import EstablishmentListingParams
from app.schemas.establishment_schema import (
    EstablishmentRequest,
    EstablishmentResponse,
    EstablishmentUpdateRequest,
)
from app.schemas.pagination import PaginatedResponse
from app.services.establishment_service import EstablishmentService

router = APIRouter(prefix="/establishments")


@router.post(
    "",
    response_model=EstablishmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new establishment",
    description="Creates a new establishment.",
    responses={
        status.HTTP_400_BAD_REQUEST: {"description": "Invalid data"},
        status.HTTP_401_UNAUTHORIZED: {"description": "Missing or invalid token"},
        status.HTTP_403_FORBIDDEN: {"description": "Insufficient permissions"},
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


@router.patch(
    "/{establishment_id}",
    response_model=EstablishmentResponse,
    status_code=status.HTTP_200_OK,
    summary="Update an establishment",
    description="Partially updates one or more fields of an existing establishment.",
    responses={
        status.HTTP_400_BAD_REQUEST: {"description": "Invalid data"},
        status.HTTP_401_UNAUTHORIZED: {"description": "Missing or invalid token"},
        status.HTTP_403_FORBIDDEN: {"description": "Insufficient permissions"},
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
    description="Returns all establishments available for a manager to register with."
    "Supports optional search filtering by establishment name or address.",
    responses={
        status.HTTP_400_BAD_REQUEST: {"description": "Invalid query parameters"},
        status.HTTP_401_UNAUTHORIZED: {"description": "Missing or invalid token"},
    },
)
async def get_establishments(
    page: int = Query(default=1, ge=1, description="Page number, starting at 1."),
    page_size: int = Query(
        default=20,
        ge=1,
        le=100,
        description="Number of establishments per page (max 100).",
    ),
    params: EstablishmentListingParams = Depends(),
    service: EstablishmentService = Depends(get_establishment_service),
    _: UserActor = Depends(require_any),
) -> PaginatedResponse[EstablishmentResponse]:
    result = await service.get_establishments_paginated(
        page=page, page_size=page_size, params=params
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
        status.HTTP_401_UNAUTHORIZED: {"description": "Missing or invalid token"},
        status.HTTP_403_FORBIDDEN: {"description": "Insufficient permissions"},
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
