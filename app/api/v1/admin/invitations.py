from uuid import UUID

from fastapi import APIRouter, Depends, Response, status

from app.api.v1.params import AUTH_RESPONSES
from app.core.dependencies import get_admin_service, require_admin
from app.domain.user import UserActor, UserRole
from app.schemas.auth.admin_schema import InviteAdminRequest, InviteUserResponse
from app.services.admin_service import AdminService

router = APIRouter()


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
    _admin: UserActor = Depends(require_admin),
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
    _admin: UserActor = Depends(require_admin),
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
    _admin: UserActor = Depends(require_admin),
) -> Response:
    await service.resend_invite(user_id)
    return Response(status_code=status.HTTP_202_ACCEPTED)
