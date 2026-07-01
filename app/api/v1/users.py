from fastapi import APIRouter, Depends, Query, status

from app.api.v1.params import PaginatedQueryParams
from app.core.dependencies import (
    get_activity_service,
    get_current_field_worker,
    get_user_service,
    require_any,
)
from app.domain.activity import ActivityListingParams, ActivityType
from app.domain.user import UserActor
from app.schemas.activity_schema import (
    ActivityItem,
    MeasurementActivityItem,
    SubjectActivityItem,
)
from app.schemas.measurement_schema import MeasurementListItem
from app.schemas.pagination import PaginatedResponse
from app.schemas.subject_schema import SubjectSummaryResponse
from app.schemas.user_schema import (
    EstablishmentAccessRequest,
    EstablishmentWithStatusResponse,
    ProfileResponse,
    ProfileUpdateRequest,
)
from app.services.activity_service import ActivityService
from app.services.user_service import UserService

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
    description="Returns the field worker's establishments, each with its approval "
    "status. Field worker only.",
    responses={
        status.HTTP_401_UNAUTHORIZED: {"description": "Missing or invalid token"},
        status.HTTP_403_FORBIDDEN: {"description": "Caller is not a field worker"},
    },
)
async def list_my_establishments(
    actor: UserActor = Depends(get_current_field_worker),
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
    "(set to pending). Field worker only.",
    responses={
        status.HTTP_401_UNAUTHORIZED: {"description": "Missing or invalid token"},
        status.HTTP_403_FORBIDDEN: {"description": "Caller is not a field worker"},
        status.HTTP_404_NOT_FOUND: {"description": "Establishment not found"},
    },
)
async def request_establishment_access(
    data: EstablishmentAccessRequest,
    actor: UserActor = Depends(get_current_field_worker),
    service: UserService = Depends(get_user_service),
) -> list[EstablishmentWithStatusResponse]:
    relations = await service.request_establishment_access(
        actor, data.establishment_ids
    )
    return [EstablishmentWithStatusResponse.model_validate(r) for r in relations]


@router.get(
    "/me/activity",
    response_model=PaginatedResponse[ActivityItem],
    status_code=status.HTTP_200_OK,
    summary="Get the current user's recent activity",
    description=(
        "Returns a paginated, date-descending feed of the caller's own "
        "subject registrations and measurement uploads. Optionally filter "
        "to a single activity type. Accessible by all authenticated roles."
    ),
    responses={
        status.HTTP_401_UNAUTHORIZED: {"description": "Missing or invalid token"},
    },
)
async def get_my_activity(
    paginated: PaginatedQueryParams = Depends(),
    type: ActivityType | None = Query(default=None),
    actor: UserActor = Depends(require_any),
    service: ActivityService = Depends(get_activity_service),
) -> PaginatedResponse[ActivityItem]:
    result = await service.get_recent_activity(
        actor,
        page=paginated.page,
        page_size=paginated.page_size,
        params=ActivityListingParams(activity_type=type),
    )
    items = [
        SubjectActivityItem(
            type=ActivityType.SUBJECT,
            occurred_at=i.occurred_at,
            subject=SubjectSummaryResponse.model_validate(i.subject),
        )
        if i.type == ActivityType.SUBJECT
        else MeasurementActivityItem(
            type=ActivityType.MEASUREMENT,
            occurred_at=i.occurred_at,
            measurement=MeasurementListItem.model_validate(i.measurement),
        )
        for i in result.items
    ]
    return PaginatedResponse[ActivityItem](
        items=items,
        total=result.total,
        page=result.page,
        page_size=result.page_size,
        total_pages=result.total_pages,
    )
