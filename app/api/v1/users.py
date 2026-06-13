from fastapi import APIRouter, Depends, status

from app.core.dependencies import (
    get_current_manager,
    get_user_service,
    require_any,
)
from app.domain.user import UserActor
from app.schemas.user_schema import (
    EstablishmentAccessRequest,
    EstablishmentWithStatusResponse,
    ProfileResponse,
    ProfileUpdateRequest,
)
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
    return ProfileResponse.model_validate(profile)


@router.patch(
    "/me",
    response_model=ProfileResponse,
    status_code=status.HTTP_200_OK,
    summary="Edit own profile",
    description="Updates the authenticated user's editable fields (name, "
    "last_name). Other fields (email, role, status) are rejected.",
    responses={
        status.HTTP_400_BAD_REQUEST: {"description": "No editable field provided"},
        status.HTTP_401_UNAUTHORIZED: {"description": "Missing or invalid token"},
        status.HTTP_404_NOT_FOUND: {
            "description": "Authenticated user no longer exists"
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "description": "Invalid value or attempt to edit a non-editable field"
        },
    },
)
async def update_my_profile(
    data: ProfileUpdateRequest,
    actor: UserActor = Depends(require_any),
    service: UserService = Depends(get_user_service),
) -> ProfileResponse:
    profile = await service.update_profile(actor, data)
    return ProfileResponse.model_validate(profile)


@router.get(
    "/me/establishments",
    response_model=list[EstablishmentWithStatusResponse],
    status_code=status.HTTP_200_OK,
    summary="List own establishment relations",
    description="Returns the manager's establishments, each with its approval "
    "status. Manager only.",
    responses={
        status.HTTP_401_UNAUTHORIZED: {"description": "Missing or invalid token"},
        status.HTTP_403_FORBIDDEN: {"description": "Caller is not a manager"},
    },
)
async def list_my_establishments(
    actor: UserActor = Depends(get_current_manager),
    service: UserService = Depends(get_user_service),
) -> list[EstablishmentWithStatusResponse]:
    relations = await service.get_own_establishments(actor)
    return [EstablishmentWithStatusResponse.model_validate(r) for r in relations]


@router.post(
    "/me/establishments",
    response_model=list[EstablishmentWithStatusResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Request establishment access",
    description="Requests access to one or more establishments. Idempotent: "
    "already-approved/pending stay unchanged, rejected ones are re-requested "
    "(set to pending). Manager only.",
    responses={
        status.HTTP_401_UNAUTHORIZED: {"description": "Missing or invalid token"},
        status.HTTP_403_FORBIDDEN: {"description": "Caller is not a manager"},
        status.HTTP_404_NOT_FOUND: {"description": "Establishment not found"},
    },
)
async def request_establishment_access(
    data: EstablishmentAccessRequest,
    actor: UserActor = Depends(get_current_manager),
    service: UserService = Depends(get_user_service),
) -> list[EstablishmentWithStatusResponse]:
    relations = await service.request_establishment_access(
        actor, data.establishment_ids
    )
    return [EstablishmentWithStatusResponse.model_validate(r) for r in relations]
