from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.v1.params import AUTH_RESPONSES, PaginatedQueryParams
from app.core.dependencies import get_admin_service, require_admin_or_superadmin
from app.domain.user import UserActor, UserRole, UserStatus
from app.schemas.auth.admin_schema import FullUserAdminView, PaginatedUsersResponse
from app.services.admin_service import AdminService

router = APIRouter()


@router.get(
    "/users",
    response_model=PaginatedUsersResponse,
    status_code=status.HTTP_200_OK,
    summary="List registered users",
    description="Returns a paginated list of users, optionally filtered by role or "
    "status, or searching by name, last name or email. Accessible by admins only.",
    responses=AUTH_RESPONSES,
)
async def list_users(
    paginated: PaginatedQueryParams = Depends(),
    role: UserRole | None = Query(default=None, description="Filter by role."),
    status_filter: UserStatus | None = Query(
        default=None, alias="status", description="Filter by status."
    ),
    search: str | None = Query(default=None, max_length=100),
    _admin: UserActor = Depends(require_admin_or_superadmin),
    service: AdminService = Depends(get_admin_service),
) -> PaginatedUsersResponse:
    result = await service.get_users_paginated(
        page=paginated.page,
        page_size=paginated.page_size,
        role=role,
        status=status_filter,
        search=search,
    )
    return PaginatedUsersResponse.model_validate(result)


@router.get(
    "/users/{user_id}",
    response_model=FullUserAdminView,
    status_code=status.HTTP_200_OK,
    summary="Get a user's profile information.",
    description="Returns all the information related to a user. "
    "Accessible by admins only.",
    responses={
        **AUTH_RESPONSES,
        status.HTTP_404_NOT_FOUND: {"description": "User not found"},
    },
)
async def get_user(
    user_id: UUID,
    _admin: UserActor = Depends(require_admin_or_superadmin),
    service: AdminService = Depends(get_admin_service),
) -> FullUserAdminView:
    """Return full profile data for the given user, including establishments.

    Raises:
        UserNotFoundError: If no user with user_id exists.
    """
    result = await service.get_user_info(user_id)
    return FullUserAdminView.model_validate(result)
