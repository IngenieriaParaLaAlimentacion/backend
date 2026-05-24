from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.core.dependencies import get_current_manager, get_subject_service
from app.domain import UserActor
from app.schemas.pagination import PaginatedResponse
from app.schemas.subject_schema import (
    SubjectRequest,
    SubjectResponse,
    SubjectSummaryResponse,
    SubjectUpdateRequest,
)
from app.services.subject_service import SubjectService

router = APIRouter(prefix="/subjects", tags=["Subjects"])


@router.post(
    "",
    response_model=SubjectResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new subject",
    description="Creates a new subject. Accessible by establishment managers only.",
    responses={
        status.HTTP_400_BAD_REQUEST: {"description": "Invalid data"},
        status.HTTP_401_UNAUTHORIZED: {"description": "Missing or invalid token"},
        status.HTTP_403_FORBIDDEN: {"description": "Insufficient permissions"},
        status.HTTP_409_CONFLICT: {"description": "Subject already exists"},
    },
)
async def create_subject(
    data: SubjectRequest,
    manager: UserActor = Depends(get_current_manager),
    service: SubjectService = Depends(get_subject_service),
) -> SubjectResponse:
    """Register a new subject."""
    subject = await service.create_subject(data, actor_id=manager.user_id)
    return SubjectResponse.model_validate(subject)


@router.get(
    "/{subject_id}",
    response_model=SubjectResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a subject by ID",
    description="Returns a subject's data. Accessible by establishment managers only.",
    responses={
        status.HTTP_401_UNAUTHORIZED: {"description": "Missing or invalid token"},
        status.HTTP_403_FORBIDDEN: {"description": "Insufficient permissions"},
        status.HTTP_404_NOT_FOUND: {"description": "Subject not found"},
    },
)
async def get_subject(
    subject_id: UUID,
    _manager: UserActor = Depends(get_current_manager),
    service: SubjectService = Depends(get_subject_service),
) -> SubjectResponse:
    """Return a subject by id."""
    subject = await service.get_subject(subject_id)
    return SubjectResponse.model_validate(subject)


@router.get(
    "",
    response_model=PaginatedResponse[SubjectSummaryResponse],
    status_code=status.HTTP_200_OK,
    summary="List subjects",
    description="Returns a paginated list of subjects ordered by creation date. "
    "Supports optional search filtering by name, last name, or DNI.",
    responses={
        status.HTTP_401_UNAUTHORIZED: {"description": "Missing or invalid token"},
        status.HTTP_403_FORBIDDEN: {"description": "Insufficient permissions"},
    },
)
async def list_subjects(
    page: int = Query(default=1, ge=1, description="Page number, starting at 1."),
    page_size: int = Query(
        default=20, ge=1, le=100, description="Results per page (max 100)."
    ),
    search: str | None = Query(default=None, max_length=100),
    _manager: UserActor = Depends(get_current_manager),
    service: SubjectService = Depends(get_subject_service),
) -> PaginatedResponse[SubjectSummaryResponse]:
    result = await service.get_subject_listing(
        page=page, page_size=page_size, search=search
    )

    return PaginatedResponse[SubjectSummaryResponse](
        items=[
            SubjectSummaryResponse.model_validate(subject) for subject in result.items
        ],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
        total_pages=result.total_pages,
    )


@router.patch(
    "/{subject_id}",
    response_model=SubjectResponse,
    status_code=status.HTTP_200_OK,
    summary="Update a subject",
    description="Partially updates a subject's data. "
    "Accessible by establishment managers only.",
    responses={
        status.HTTP_400_BAD_REQUEST: {"description": "No fields provided"},
        status.HTTP_401_UNAUTHORIZED: {"description": "Missing or invalid token"},
        status.HTTP_403_FORBIDDEN: {"description": "Insufficient permissions"},
        status.HTTP_404_NOT_FOUND: {"description": "Subject not found"},
        status.HTTP_409_CONFLICT: {
            "description": "DNI already belongs to another subject"
        },
    },
)
async def update_subject(
    subject_id: UUID,
    data: SubjectUpdateRequest,
    manager: UserActor = Depends(get_current_manager),
    service: SubjectService = Depends(get_subject_service),
) -> SubjectResponse:
    subject = await service.update_subject(subject_id, data, actor_id=manager.user_id)
    return SubjectResponse.model_validate(subject)
