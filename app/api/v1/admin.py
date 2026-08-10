from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.v1.params import AUTH_RESPONSES, PaginatedQueryParams
from app.core.dependencies import (
    get_admin_service,
    get_current_admin,
)
from app.domain.user import UserActor, UserRole, UserStatus
from app.schemas.admin_schema import (
    AdminSubjectDetailResponse,
    EstablishmentAccessRequest,
    FullUserAdminView,
    InviteAdminRequest,
    InviteUserResponse,
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
    responses=AUTH_RESPONSES,
)
async def list_users(
    paginated: PaginatedQueryParams = Depends(),
    role: UserRole | None = Query(default=None, description="Filter by role."),
    status_filter: UserStatus | None = Query(
        default=None, alias="status", description="Filter by status."
    ),
    search: str | None = Query(default=None, max_length=100),
    _admin: UserActor = Depends(get_current_admin),
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
        **AUTH_RESPONSES,
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
        **AUTH_RESPONSES,
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
    "/field-worker/{user_id}/approve",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Accept a field worker",
    description="Activates the field worker's account. Accessible by admins only.",
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "description": "Target user is not a field worker, or is not pending"
        },
        **AUTH_RESPONSES,
        status.HTTP_404_NOT_FOUND: {"description": "Field worker not found"},
    },
)
async def approve_field_worker(
    user_id: UUID,
    _admin: UserActor = Depends(get_current_admin),
    service: AdminService = Depends(get_admin_service),
) -> Response:
    await service.approve_field_worker(user_id)
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
        **AUTH_RESPONSES,
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
        **AUTH_RESPONSES,
        status.HTTP_404_NOT_FOUND: {"description": "Subject not found"},
    },
)
async def get_subject_detail(
    subject_id: UUID,
    paginated: PaginatedQueryParams = Depends(),
    _admin: UserActor = Depends(get_current_admin),
    service: AdminService = Depends(get_admin_service),
) -> AdminSubjectDetailResponse:
    subject, history = await service.get_subject_detail(
        subject_id,
        history_page=paginated.page,
        history_page_size=paginated.page_size,
    )
    return AdminSubjectDetailResponse.from_domain(subject, history)


@router.post(
    "/invite-admin",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=InviteUserResponse,
    summary="Invite admin",
    description="Creates an admin user and sends a password setup link by email. "
    "Returns the created user's id for the resend-invitation flow.",
    responses={
        status.HTTP_202_ACCEPTED: {
            "description": "Invitation sent; created user's id returned."
        },
        status.HTTP_409_CONFLICT: {"description": "Email already exists"},
        status.HTTP_502_BAD_GATEWAY: {
            "description": "Invitation email could not be delivered"
        },
        **AUTH_RESPONSES,
    },
)
async def invite_admin(
    data: InviteAdminRequest,
    service: AdminService = Depends(get_admin_service),
    _admin: UserActor = Depends(get_current_admin),
) -> InviteUserResponse:
    user_id = await service.invite_user(data, role=UserRole.ADMIN)
    return InviteUserResponse(user_id=user_id)


@router.post(
    "/invite-analyst",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=InviteUserResponse,
    summary="Invite analyst",
    description="Creates an analyst user and sends a password setup link by email. "
    "Returns the created user's id for the resend-invitation flow.",
    responses={
        status.HTTP_202_ACCEPTED: {"description": "Invitation sent successfully"},
        status.HTTP_409_CONFLICT: {"description": "Email already exists"},
        status.HTTP_502_BAD_GATEWAY: {
            "description": "Invitation email could not be delivered"
        },
        **AUTH_RESPONSES,
    },
)
async def invite_analyst(
    data: InviteAdminRequest,
    service: AdminService = Depends(get_admin_service),
    _admin: UserActor = Depends(get_current_admin),
) -> InviteUserResponse:
    user_id = await service.invite_user(data, role=UserRole.ANALYST)
    return InviteUserResponse(user_id=user_id)


@router.patch(
    "/users/{user_id}/resend-invite",
    status_code=status.HTTP_202_ACCEPTED,
    response_class=Response,
    summary="Re-send invitation to admin/analyst user",
    description="Re-send invitation to an already invited admin/analyst",
    responses={
        status.HTTP_202_ACCEPTED: {"description": "Invitation re-sent successfully"},
        status.HTTP_400_BAD_REQUEST: {
            "description": "User is not pending, or is not a valid user"
        },
        status.HTTP_404_NOT_FOUND: {"description": "User not found"},
        status.HTTP_502_BAD_GATEWAY: {
            "description": "Invitation email could not be delivered"
        },
        **AUTH_RESPONSES,
    },
)
async def resend_invite(
    user_id: UUID,
    service: AdminService = Depends(get_admin_service),
    _admin: UserActor = Depends(get_current_admin),
) -> Response:
    await service.resend_invite(user_id)
    return Response(status_code=status.HTTP_202_ACCEPTED)


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
    _admin: UserActor = Depends(get_current_admin),
    service: AdminService = Depends(get_admin_service),
) -> FullUserAdminView:
    """Return full profile data for the given user, including establishments.

    Raises:
        UserNotFoundError: If no user with user_id exists.
    """
    result = await service.get_user_info(user_id)
    return FullUserAdminView.model_validate(result)
