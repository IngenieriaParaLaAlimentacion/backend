from uuid import UUID

from fastapi import APIRouter, Depends, Response, status

from app.core.dependencies import (
    get_admin_service,
    get_current_admin,
)
from app.domain.user import UserActor, UserRole
from app.schemas.admin_schema import EstablishmentAccessRequest, InviteAdminRequest
from app.services.admin_service import AdminService

router = APIRouter(prefix="/admin")


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
