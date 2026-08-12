from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.v1.params import AUTH_RESPONSES, PaginatedQueryParams
from app.core.dependencies import get_admin_service, require_admin_or_superadmin
from app.domain.user import UserActor
from app.schemas.admin_schema import AdminSubjectDetailResponse
from app.services.admin_service import AdminService

router = APIRouter()


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
    _admin: UserActor = Depends(require_admin_or_superadmin),
    service: AdminService = Depends(get_admin_service),
) -> AdminSubjectDetailResponse:
    subject, history = await service.get_subject_detail(
        subject_id,
        history_page=paginated.page,
        history_page_size=paginated.page_size,
    )
    return AdminSubjectDetailResponse.from_domain(subject, history)
