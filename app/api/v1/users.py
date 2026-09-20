from typing import Annotated

from fastapi import APIRouter, Depends, Path, Response, status

from app.api.v1.params import AUTH_RESPONSES, ActivityListingQuery, PaginatedQueryParams
from app.core.dependencies import (
    get_activity_service,
    get_device_service,
    get_user_service,
    require_any,
)
from app.domain.user import UserActor
from app.schemas.activity_schema import ActivityItemResponse
from app.schemas.auth.user_schema import (
    EstablishmentIdsRequest,
    EstablishmentWithStatusResponse,
    ProfileResponse,
    ProfileUpdateRequest,
)
from app.schemas.notifications.device_schema import (
    DeviceRegistrationRequest,
    DeviceResponse,
)
from app.schemas.pagination import PaginatedResponse
from app.services.activity_service import ActivityService
from app.services.auth.user_service import UserService
from app.services.notifications.device_service import DeviceService

router = APIRouter(prefix="/users")


@router.get(
    "/me",
    response_model=ProfileResponse,
    status_code=status.HTTP_200_OK,
    summary="Get own profile",
    description="Returns the authenticated user's profile. Field workers "
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
        status.HTTP_401_UNAUTHORIZED: {
            "description": "Missing or invalid authentication token"
        },
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
    description="Returns the caller's establishments, each with its approval "
    "status. Accessible by all authenticated roles.",
    responses=AUTH_RESPONSES,
)
async def list_my_establishments(
    actor: UserActor = Depends(require_any),
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
    "(set to pending). Accessible by all authenticated roles.",
    responses={
        **AUTH_RESPONSES,
        status.HTTP_404_NOT_FOUND: {"description": "Establishment not found"},
    },
)
async def request_establishment_access(
    data: EstablishmentIdsRequest,
    actor: UserActor = Depends(require_any),
    service: UserService = Depends(get_user_service),
) -> list[EstablishmentWithStatusResponse]:
    relations = await service.request_establishment_access(
        actor, data.establishment_ids
    )
    return [EstablishmentWithStatusResponse.model_validate(r) for r in relations]


@router.get(
    "/me/activity",
    response_model=PaginatedResponse[ActivityItemResponse],
    status_code=status.HTTP_200_OK,
    summary="Get the current user's recent activity",
    description=(
        "Returns a paginated, date-descending feed of the caller's own "
        "subject registrations, measurement uploads, survey responses, and "
        "food movements (intakes and outflows). Optionally filter to one or "
        "more activity types by repeating `type`; the server merges, sorts "
        "and paginates them as a single feed. Accessible by all "
        "authenticated roles."
    ),
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "description": "Missing or invalid authentication token"
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "description": "Unknown activity type, or invalid pagination values"
        },
    },
)
async def get_my_activity(
    paginated: PaginatedQueryParams = Depends(),
    activity_query: ActivityListingQuery = Depends(),
    actor: UserActor = Depends(require_any),
    service: ActivityService = Depends(get_activity_service),
) -> PaginatedResponse[ActivityItemResponse]:
    result = await service.get_recent_activity(
        actor,
        page=paginated.page,
        page_size=paginated.page_size,
        params=activity_query.to_domain(),
    )
    return PaginatedResponse[ActivityItemResponse](
        items=[ActivityItemResponse.model_validate(i) for i in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
        total_pages=result.total_pages,
    )


@router.post(
    "/me/devices",
    response_model=DeviceResponse,
    status_code=status.HTTP_200_OK,
    summary="Register a push-notification installation",
    responses={
        **AUTH_RESPONSES,
        status.HTTP_404_NOT_FOUND: {
            "description": "Authenticated user no longer exists"
        },
    },
)
async def register_my_device(
    data: DeviceRegistrationRequest,
    actor: UserActor = Depends(require_any),
    service: DeviceService = Depends(get_device_service),
) -> DeviceResponse:
    device = await service.register(actor, data)
    return DeviceResponse.model_validate(device)


@router.delete(
    "/me/devices/{installation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Unregister a push-notification installation",
    responses=AUTH_RESPONSES,
)
async def unregister_my_device(
    installation_id: Annotated[str, Path(min_length=1, max_length=255)],
    actor: UserActor = Depends(require_any),
    service: DeviceService = Depends(get_device_service),
) -> Response:
    await service.unregister(actor, installation_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch(
    "/me/establishments/withdraw",
    response_model=list[EstablishmentWithStatusResponse],
    status_code=status.HTTP_200_OK,
    summary="Withdraw establishment access",
    description="Withdraws the caller's own access to one or more "
    "establishments. Only relations currently approved or pending can be "
    "withdrawn. Accessible by all authenticated roles.",
    responses={
        **AUTH_RESPONSES,
        status.HTTP_404_NOT_FOUND: {
            "description": "Establishment not associated with the caller"
        },
        status.HTTP_409_CONFLICT: {
            "description": "Relation is not currently approved or pending"
        },
    },
)
async def withdraw_establishment_access(
    data: EstablishmentIdsRequest,
    actor: UserActor = Depends(require_any),
    service: UserService = Depends(get_user_service),
) -> list[EstablishmentWithStatusResponse]:
    relations = await service.withdraw_establishment_access(
        actor, data.establishment_ids
    )
    return [EstablishmentWithStatusResponse.model_validate(r) for r in relations]
