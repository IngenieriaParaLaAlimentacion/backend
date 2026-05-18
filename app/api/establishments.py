from fastapi import APIRouter, Depends, Query, status

from app.core.dependencies import get_establishment_service
from app.schemas.establishment import PaginatedEstablishmentsResponse
from app.services.establishment_service import EstablishmentService

router = APIRouter(prefix="/establishments", tags=["Establishments"])


@router.get(
    "",
    response_model=PaginatedEstablishmentsResponse,
    status_code=status.HTTP_200_OK,
    summary="List all establishments",
    description="Returns all establishments available for a manager to register with.",
)
async def get_establishments(
    page: int = Query(default=1, ge=1, description="Page number, starting at 1."),
    page_size: int = Query(
        default=20,
        ge=1,
        le=100,
        description="Number of establishments per page (max 100).",
    ),
    service: EstablishmentService = Depends(get_establishment_service),
) -> PaginatedEstablishmentsResponse:
    return await service.get_establishments_paginated(page=page, page_size=page_size)
