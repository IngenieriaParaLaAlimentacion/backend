from fastapi import APIRouter, Depends, Query, status

from app.core.dependencies import (
    get_establishment_service,
    require_any,
)
from app.domain import UserRole
from app.schemas.establishment_schema import EstablishmentResponse
from app.schemas.pagination import PaginatedResponse
from app.services.establishment_service import EstablishmentService

router = APIRouter(prefix="/establishments", tags=["Establishments"])


@router.get(
    "",
    response_model=PaginatedResponse[EstablishmentResponse],
    status_code=status.HTTP_200_OK,
    summary="List all establishments",
    description="Returns all establishments available for a manager to register with."
    "Supports optional search filtering by establishment name or address.",
)
async def get_establishments(
    page: int = Query(default=1, ge=1, description="Page number, starting at 1."),
    page_size: int = Query(
        default=20,
        ge=1,
        le=100,
        description="Number of establishments per page (max 100).",
    ),
    search: str | None = Query(default=None, max_length=100),
    service: EstablishmentService = Depends(get_establishment_service),
    _user: UserRole = Depends(
        require_any(
            UserRole.ESTABLISHMENT_MANAGER, UserRole.ADMIN, UserRole.PROFESSIONAL
        )
    ),
) -> PaginatedResponse[EstablishmentResponse]:
    result = await service.get_establishments_paginated(
        page=page, page_size=page_size, search=search
    )

    return PaginatedResponse[EstablishmentResponse](
        items=[EstablishmentResponse.model_validate(estab) for estab in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
        total_pages=result.total_pages,
    )
