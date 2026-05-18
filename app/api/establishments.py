from typing import List

from fastapi import APIRouter, Depends, status

from app.core.dependencies import get_establishment_service
from app.schemas.establishment import EstablishmentResponse
from app.services.establishment_service import EstablishmentService

router = APIRouter(prefix="/establishments", tags=["Establishments"])


@router.get(
    "",
    response_model=List[EstablishmentResponse],
    status_code=status.HTTP_200_OK,
    summary="List all establishments",
    description="Returns all establishments available for a manager to register with.",
)
async def get_establishments(
    service: EstablishmentService = Depends(get_establishment_service),
) -> List[EstablishmentResponse]:
    establishments = await service.get_all()
    return [EstablishmentResponse.model_validate(e) for e in establishments]
