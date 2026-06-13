from fastapi import APIRouter, Depends, status

from app.core.dependencies import get_user_service, require_any
from app.domain.user import UserActor
from app.schemas.user_schema import EstablishmentWithStatusResponse, ProfileResponse
from app.services.user_service import UserService

router = APIRouter(prefix="/users")


@router.get(
    "/me",
    response_model=ProfileResponse,
    status_code=status.HTTP_200_OK,
    summary="Get own profile",
    description="Returns the authenticated user's profile. Establishment managers "
    "also receive their associated establishments, each with its approval status.",
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "description": "Missing or invalid authentication token"
        },
        status.HTTP_404_NOT_FOUND: {
            "description": "Authenticated user no longer exists"
        },
    },
)
async def get_my_profile(
    actor: UserActor = Depends(require_any),
    service: UserService = Depends(get_user_service),
) -> ProfileResponse:
    profile = await service.get_profile(actor)
    return ProfileResponse(
        id=profile.id,
        email=profile.email,
        name=profile.name,
        last_name=profile.last_name,
        role=profile.role,
        establishments=(
            None
            if profile.establishments is None
            else [
                EstablishmentWithStatusResponse(
                    id=establishment.id,
                    name=establishment.name,
                    address=establishment.address,
                    status=establishment.status,
                )
                for establishment in profile.establishments
            ]
        ),
    )
