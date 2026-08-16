from uuid import UUID

from fastapi import APIRouter, Depends, Response, status

from app.api.v1.params import (
    AUTH_RESPONSES,
    EstablishmentCreationRequestListingQuery,
    PaginatedQueryParams,
)
from app.core.dependencies import get_establishment_service, require_admin
from app.domain.user import UserActor
from app.schemas.establishments.establishment_schema import (
    EstablishmentApprovalResponse,
    EstablishmentCreationRequestAdminView,
    EstablishmentRequest,
    EstablishmentRequestRejection,
)
from app.schemas.pagination import PaginatedResponse
from app.services.establishments.establishment_service import EstablishmentService

router = APIRouter()


@router.get(
    "/establishment-requests",
    response_model=PaginatedResponse[EstablishmentCreationRequestAdminView],
    status_code=status.HTTP_200_OK,
    summary="List establishment creation requests",
    description="Returns a paginated list of establishment-missing "
    "notifications, optionally filtered by status/city/province or searched "
    "by reported name/address or requester identity, including the "
    "requesting field worker's identity. Accessible by admins only.",
    responses=AUTH_RESPONSES,
)
async def list_establishment_requests(
    paginated: PaginatedQueryParams = Depends(),
    query: EstablishmentCreationRequestListingQuery = Depends(),
    _admin: UserActor = Depends(require_admin),
    service: EstablishmentService = Depends(get_establishment_service),
) -> PaginatedResponse[EstablishmentCreationRequestAdminView]:
    result = await service.list_establishment_requests_paginated(
        page=paginated.page,
        page_size=paginated.page_size,
        params=query.to_domain(),
    )
    return PaginatedResponse[EstablishmentCreationRequestAdminView].model_validate(
        result, from_attributes=True
    )


@router.patch(
    "/establishment-requests/{request_id}/approve",
    response_model=EstablishmentApprovalResponse,
    status_code=status.HTTP_200_OK,
    summary="Approve an establishment creation request",
    description="Approves the request using the admin-provided final data, "
    "creating a new establishment or reusing an existing one with the same "
    "place_id. The field worker's access to it is left pending a separate "
    "admin review; they're notified by email that the establishment was "
    "created. Accessible by admins only.",
    responses={
        **AUTH_RESPONSES,
        status.HTTP_404_NOT_FOUND: {"description": "Request not found"},
        status.HTTP_409_CONFLICT: {"description": "Request already reviewed"},
    },
)
async def approve_request(
    request_id: UUID,
    data: EstablishmentRequest,
    admin: UserActor = Depends(require_admin),
    service: EstablishmentService = Depends(get_establishment_service),
) -> EstablishmentApprovalResponse:
    establishment, reused = await service.approve_creation_request(
        request_id, data, reviewer_id=admin.user_id
    )
    return EstablishmentApprovalResponse(
        id=establishment.id,
        name=establishment.name,
        formatted_address=establishment.formatted_address,
        latitude=establishment.latitude,
        longitude=establishment.longitude,
        place_id=establishment.place_id,
        city=establishment.city,
        province=establishment.province,
        reused=reused,
    )


@router.patch(
    "/establishment-requests/{request_id}/reject",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Reject an establishment creation request",
    description="Rejects the request and notifies the requesting field "
    "worker by email, optionally including the admin's reason. No "
    "establishment is created or linked. Accessible by admins only.",
    responses={
        **AUTH_RESPONSES,
        status.HTTP_404_NOT_FOUND: {"description": "Request not found"},
        status.HTTP_409_CONFLICT: {"description": "Request already reviewed"},
    },
)
async def reject_request(
    request_id: UUID,
    data: EstablishmentRequestRejection,
    admin: UserActor = Depends(require_admin),
    service: EstablishmentService = Depends(get_establishment_service),
) -> Response:
    await service.reject_creation_request(
        request_id, reason=data.reason, reviewer_id=admin.user_id
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
