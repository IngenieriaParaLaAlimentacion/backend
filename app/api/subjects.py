from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.core.dependencies import get_current_manager, get_subject_service
from app.domain import UserActor
from app.schemas.subject_schema import SubjectRequest, SubjectResponse
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
    current_user: UserActor = Depends(get_current_manager),
    service: SubjectService = Depends(get_subject_service),
) -> SubjectResponse:
    """Register a new subject."""
    subject = await service.create_subject(data)
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
    current_user: UserActor = Depends(get_current_manager),
    service: SubjectService = Depends(get_subject_service),
) -> SubjectResponse:
    """Return a subject by id."""
    subject = await service.get_subject(subject_id)
    return SubjectResponse.model_validate(subject)
