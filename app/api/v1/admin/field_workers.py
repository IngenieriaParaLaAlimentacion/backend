from uuid import UUID

from fastapi import APIRouter, Depends, Response, status

from app.api.v1.params import AUTH_RESPONSES, PaginatedQueryParams
from app.core.dependencies import get_admin_service, require_admin
from app.domain.user import UserActor
from app.schemas.auth.admin_schema import (
    PendingEstablishmentsResponse,
    UserAccessRequest,
)
from app.schemas.auth.user_schema import EstablishmentAccessRequest
from app.services.admin_service import AdminService

router = APIRouter()


@router.patch(
    "/field-worker/{user_id}/establishments/approve",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Approve establishment access for a field worker",
    description="Approves the given establishments for an active field worker. "
    "Accessible by admins only.",
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "description": "Target user's account is not active"
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
    _admin: UserActor = Depends(require_admin),
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
    _admin: UserActor = Depends(require_admin),
    service: AdminService = Depends(get_admin_service),
) -> Response:
    await service.reject_establishments(user_id, data.establishment_ids)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch(
    "/field-worker/{user_id}/approve",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Accept a field worker and the selected establishments",
    description="Activates the field worker's account and approves the given "
    "establishments. `establishment_ids` may be empty, in which case the "
    "account is activated and every establishment request stays pending.",
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "description": "Target user is not a field worker, or is not pending"
        },
        **AUTH_RESPONSES,
        status.HTTP_404_NOT_FOUND: {
            "description": "Field worker not found, or an establishment was not "
            "requested by this field worker"
        },
    },
)
async def approve_field_worker(
    user_id: UUID,
    data: UserAccessRequest,
    _admin: UserActor = Depends(require_admin),
    service: AdminService = Depends(get_admin_service),
) -> Response:
    await service.approve_field_worker(user_id, data.establishment_ids)
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
    _admin: UserActor = Depends(require_admin),
    service: AdminService = Depends(get_admin_service),
) -> Response:
    await service.reject_field_worker(user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/field-worker/establishments/pending",
    response_model=PendingEstablishmentsResponse,
    status_code=status.HTTP_200_OK,
    summary="List field workers with pending establishment access",
    description="Returns a paginated list of active field workers that have at "
    "least one establishment request awaiting review, each carrying only their "
    "pending establishments, plus the total number of pending requests across "
    "all of them. Accessible by admins only.",
    responses=AUTH_RESPONSES,
)
async def get_pending_establishment_requests(
    paginated: PaginatedQueryParams = Depends(),
    _admin: UserActor = Depends(require_admin),
    service: AdminService = Depends(get_admin_service),
) -> PendingEstablishmentsResponse:
    result, total_pending = await service.get_pending_establishment_requests(
        page=paginated.page, page_size=paginated.page_size
    )
    return PendingEstablishmentsResponse.from_domain(result, total_pending)
