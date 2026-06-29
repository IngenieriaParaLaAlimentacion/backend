from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from app.core.dependencies import (
    get_admin_service,
    get_current_admin,
)
from app.domain.user import UserActor, UserRole, UserStatus
from app.schemas.admin_schema import (
    AdminSubjectDetailResponse,
    EstablishmentAccessRequest,
    InviteAdminRequest,
    PaginatedUsersResponse,
)
from app.services.admin_service import AdminService

router = APIRouter(prefix="/admin")


@router.get(
    "/users",
    response_model=PaginatedUsersResponse,
    status_code=status.HTTP_200_OK,
    summary="List registered users",
    description="Returns a paginated list of users, optionally filtered by role or "
    "status, or searching by name, last name or email. Accessible by admins only.",
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
    return PaginatedUsersResponse.model_validate(result)


@router.patch(
    "/field-worker/{user_id}/establishments/approve",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Approve establishment access for a field worker",
    description="Approves the given establishments for the field worker and "
    "activates the field worker's account. Accessible by admins only.",
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "description": "Target user is not a field worker"
        },
        status.HTTP_401_UNAUTHORIZED: {
            "description": "Missing or invalid authentication token"
        },
        status.HTTP_403_FORBIDDEN: {
            "description": "Authenticated user does not have admin privileges"
        },
        status.HTTP_404_NOT_FOUND: {
            "description": "Field worker or establishment not found"
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
    "/field-worker/{user_id}/establishments/reject",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Reject establishment access for a field worker",
    description="Rejects the given establishments for the field worker. "
    "Does not affect the field worker's account status. Accessible by admins only.",
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "description": "Target user is not a field worker"
        },
        status.HTTP_401_UNAUTHORIZED: {
            "description": "Missing or invalid authentication token"
        },
        status.HTTP_403_FORBIDDEN: {
            "description": "Authenticated user does not have admin privileges"
        },
        status.HTTP_404_NOT_FOUND: {
            "description": "Field worker or establishment not found"
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


@router.patch(
    "/field-worker/{user_id}/reject",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Reject all access for a field worker",
    description="Rejects all establishments for the given field worker. "
    "Makes the user status INACTIVE. Accessible by admins only.",
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "description": "Target user is not a field worker"
        },
        status.HTTP_401_UNAUTHORIZED: {
            "description": "Missing or invalid authentication token"
        },
        status.HTTP_403_FORBIDDEN: {
            "description": "Authenticated user does not have admin privileges"
        },
        status.HTTP_404_NOT_FOUND: {"description": "Field worker not found"},
    },
)
async def reject_field_worker(
    user_id: UUID,
    _admin: UserActor = Depends(get_current_admin),
    service: AdminService = Depends(get_admin_service),
) -> Response:
    await service.reject_field_worker(user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/subjects/{subject_id}",
    response_model=AdminSubjectDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Get subject detail",
    description="Returns full subject data including paginated event history. "
    "Accessible by admins only.",
    responses={
        status.HTTP_401_UNAUTHORIZED: {"description": "Missing or invalid token"},
        status.HTTP_403_FORBIDDEN: {"description": "Insufficient permissions"},
        status.HTTP_404_NOT_FOUND: {"description": "Subject not found"},
    },
)
async def get_subject_detail(
    subject_id: UUID,
    history_page: int = Query(default=1, ge=1),
    history_page_size: int = Query(default=20, ge=1, le=100),
    _admin: UserActor = Depends(get_current_admin),
    service: AdminService = Depends(get_admin_service),
) -> AdminSubjectDetailResponse:
    subject, history = await service.get_subject_detail(
        subject_id,
        history_page=history_page,
        history_page_size=history_page_size,
    )
    return AdminSubjectDetailResponse.from_domain(subject, history)


@router.post(
    "/invite-admin",
    status_code=status.HTTP_202_ACCEPTED,
    response_class=Response,
    summary="Invite admin",
    description="Creates an admin user and sends a password setup link by email.",
    responses={
        status.HTTP_202_ACCEPTED: {"description": "Invitation sent successfully"},
        status.HTTP_409_CONFLICT: {"description": "Email already exists"},
        status.HTTP_403_FORBIDDEN: {"description": "Insufficient permissions"},
    },
)
async def invite_admin(
    data: InviteAdminRequest,
    service: AdminService = Depends(get_admin_service),
    _admin: UserActor = Depends(get_current_admin),
) -> Response:
    await service.invite_user(data, role=UserRole.ADMIN)
    return Response(status_code=status.HTTP_202_ACCEPTED)


@router.post(
    "/invite-analyst",
    status_code=status.HTTP_202_ACCEPTED,
    response_class=Response,
    summary="Invite analyst",
    description="Creates an analyst user and sends a password setup link by email.",
    responses={
        status.HTTP_202_ACCEPTED: {"description": "Invitation sent successfully"},
        status.HTTP_401_UNAUTHORIZED: {
            "description": "Missing or invalid authentication token"
        },
        status.HTTP_403_FORBIDDEN: {"description": "Insufficient permissions"},
        status.HTTP_409_CONFLICT: {"description": "Email already exists"},
    },
)
async def invite_analyst(
    data: InviteAdminRequest,
    service: AdminService = Depends(get_admin_service),
    _admin: UserActor = Depends(get_current_admin),
) -> Response:
    await service.invite_user(data, role=UserRole.ANALYST)
    return Response(status_code=status.HTTP_202_ACCEPTED)


@router.patch(
    "/users/{user_id}/resend-invite",
    status_code=status.HTTP_202_ACCEPTED,
    response_class=Response,
    summary="Re-send invitation to admin/analyst user",
    description="Re-send invitation to an already invited admin/analyst",
)
async def resend_invite(
    user_id: UUID,
    service: AdminService = Depends(get_admin_service),
    _admin: UserActor = Depends(get_current_admin),
) -> Response:
    await service.resend_invite(user_id)
