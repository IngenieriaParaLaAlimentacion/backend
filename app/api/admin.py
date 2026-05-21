from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.core.dependencies import get_admin_service, get_current_admin
from app.domain.user import UserActor, UserRole, UserStatus
from app.schemas.admin_schema import (
    ApproveManagerRequest,
    ApproveManagerResponse,
    EstablishmentWithStatusResponse,
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
    _admin: UserActor = Depends(get_current_admin),
    service: AdminService = Depends(get_admin_service),
) -> PaginatedUsersResponse:
    result = await service.get_users_paginated(
        page=page, page_size=page_size, role=role, status=status_filter
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


@router.post(
    "/managers/{user_id}/approve",
    response_model=ApproveManagerResponse,
    status_code=status.HTTP_200_OK,
    summary="Approve a manager",
    description="Approves a manager and sets the status of each of their "
    "establishments. Establishments not included in the request are rejected. "
    "Accessible by admins only.",
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
async def approve_manager(
    user_id: UUID,
    data: ApproveManagerRequest,
    _admin: UserActor = Depends(get_current_admin),
    service: AdminService = Depends(get_admin_service),
) -> ApproveManagerResponse:
    result = await service.approve_manager(user_id, data.approved_establishment_ids)
    return ApproveManagerResponse(
        id=result.id,
        email=result.email,
        name=result.name,
        last_name=result.last_name,
        role=result.role,
        status=result.status,
        establishments=[
            EstablishmentWithStatusResponse(
                id=estab.id,
                name=estab.name,
                address=estab.address,
                status=estab.status,
            )
            for estab in result.establishments
        ],
    )
