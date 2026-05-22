from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from app.core.dependencies import get_admin_service, get_current_admin
from app.domain.user import UserActor, UserRole, UserStatus
from app.schemas.admin_schema import (
    EstablishmentAccessRequest,
    PaginatedUsersResponse,
    UserAdminView,
)
from app.schemas.establishment_schema import EstablishmentResponse
from app.services.admin_service import AdminService

router = APIRouter(prefix="/admin", tags=["Admin"])


@router.get(
    "/users",
    response_model=PaginatedUsersResponse,
    status_code=status.HTTP_200_OK,
    summary="List registered users",
    description="Returns a paginated list of users, optionally filtered by role or "
    "status. Accessible by admins only.",
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "description": "Missing or invalid authentication token"
        },
        status.HTTP_403_FORBIDDEN: {
            "description": "Authenticated user does not have admin privileges"
        },
    },
)
async def list_users(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    role: UserRole | None = Query(default=None, description="Filter by role."),
    status_filter: UserStatus | None = Query(
        default=None, alias="status", description="Filter by status."
    ),
    search: str | None = Query(default=None, max_length=100),
    _admin: UserActor = Depends(get_current_admin),
    service: AdminService = Depends(get_admin_service),
) -> PaginatedUsersResponse:
    result = await service.get_users_paginated(
        page=page, page_size=page_size, role=role, status=status_filter, search=search
    )
    return PaginatedUsersResponse(
        items=[
            UserAdminView(
                id=user.id,
                email=user.email,
                name=user.name,
                last_name=user.last_name,
                role=user.role,
                status=user.status,
                establishments=[
                    EstablishmentResponse(
                        id=estab.id, name=estab.name, address=estab.address
                    )
                    for estab in user.establishments
                ],
            )
            for user in result.items
        ],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
        total_pages=result.total_pages,
    )


@router.patch(
    "/managers/{user_id}/establishments/approve",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Approve establishment access for a manager",
    description="Approves the given establishments for the manager and activates the "
    "manager's account. Accessible by admins only.",
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "description": "Missing or invalid authentication token"
        },
        status.HTTP_403_FORBIDDEN: {
            "description": "Authenticated user does not have admin privileges"
        },
        status.HTTP_404_NOT_FOUND: {
            "description": "Manager or establishment not found"
        },
    },
)
async def approve_establishments(
    user_id: UUID,
    data: EstablishmentAccessRequest,
    _admin: UserActor = Depends(get_current_admin),
    service: AdminService = Depends(get_admin_service),
) -> Response:
    await service.approve_establishments(user_id, data.establishment_ids)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch(
    "/managers/{user_id}/establishments/reject",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Reject establishment access for a manager",
    description="Rejects the given establishments for the manager. Does not affect "
    "the manager's account status. Accessible by admins only.",
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "description": "Missing or invalid authentication token"
        },
        status.HTTP_403_FORBIDDEN: {
            "description": "Authenticated user does not have admin privileges"
        },
        status.HTTP_404_NOT_FOUND: {
            "description": "Manager or establishment not found"
        },
    },
)
async def reject_establishments(
    user_id: UUID,
    data: EstablishmentAccessRequest,
    _admin: UserActor = Depends(get_current_admin),
    service: AdminService = Depends(get_admin_service),
) -> Response:
    await service.reject_establishments(user_id, data.establishment_ids)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
