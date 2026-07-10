from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.v1.params import SurveyListingQuery
from app.core.dependencies import get_survey_service, require_some
from app.data.fies_template import build_fies_template
from app.domain import UserActor
from app.domain.user import UserRole
from app.schemas.pagination import PaginatedResponse
from app.schemas.survey_schema import (
    SurveyCreateRequest,
    SurveyListItem,
    SurveyResponse,
    SurveyStatusRequest,
    SurveyTemplateResponse,
    SurveyUpdateRequest,
)
from app.services.survey_service import SurveyService

router = APIRouter(prefix="/surveys")

require_survey_author = require_some(
    UserRole.ADMIN, UserRole.ANALYST, UserRole.SUPERADMIN
)

_AUTH_RESPONSES = {
    status.HTTP_401_UNAUTHORIZED: {"description": "Missing or invalid token"},
    status.HTTP_403_FORBIDDEN: {"description": "Insufficient permissions"},
}


@router.post(
    "",
    response_model=SurveyResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a survey",
    description=(
        "Create a FIES or custom survey with its ordered questions, options and "
        "audience. Accessible by admins and analysts."
    ),
    responses={
        **_AUTH_RESPONSES,
        status.HTTP_400_BAD_REQUEST: {"description": "Invalid survey structure"},
        status.HTTP_404_NOT_FOUND: {"description": "Targeted establishment not found"},
        status.HTTP_409_CONFLICT: {"description": "Survey name already exists"},
    },
)
async def create_survey(
    data: SurveyCreateRequest,
    actor: UserActor = Depends(require_survey_author),
    service: SurveyService = Depends(get_survey_service),
) -> SurveyResponse:
    survey = await service.create(data, actor)
    return SurveyResponse.model_validate(survey)


@router.get(
    "",
    response_model=PaginatedResponse[SurveyListItem],
    summary="List surveys",
    description=(
        "Paginated, filterable and sortable list of surveys. Supports name search "
        "and filtering by author, scope and active flag."
    ),
    responses=_AUTH_RESPONSES,
)
async def list_surveys(
    query: SurveyListingQuery = Depends(),
    page: int = Query(default=1, ge=1, description="Page number, starting at 1."),
    page_size: int = Query(
        default=20, ge=1, le=100, description="Results per page (max 100)."
    ),
    _: UserActor = Depends(require_survey_author),
    service: SurveyService = Depends(get_survey_service),
) -> PaginatedResponse[SurveyListItem]:
    result = await service.list_surveys(
        page=page, page_size=page_size, params=query.to_domain()
    )
    return PaginatedResponse[SurveyListItem](
        items=[SurveyListItem.model_validate(item) for item in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
        total_pages=result.total_pages,
    )


@router.get(
    "/templates/fies",
    response_model=SurveyTemplateResponse,
    summary="Get the FIES survey template",
    description=(
        "Returns the canonical 8-item FAO FIES instrument as a ready-to-edit draft "
        "(no ids). The author fills in the name before saving."
    ),
    responses=_AUTH_RESPONSES,
)
async def get_fies_template(
    _: UserActor = Depends(require_survey_author),
) -> SurveyTemplateResponse:
    return build_fies_template()


@router.get(
    "/{survey_id}",
    response_model=SurveyResponse,
    summary="Get a survey",
    description="Return a survey's full configuration with ordered questions "
    "and options.",
    responses={
        **_AUTH_RESPONSES,
        status.HTTP_404_NOT_FOUND: {"description": "Survey not found"},
    },
)
async def get_survey(
    survey_id: UUID,
    _: UserActor = Depends(require_survey_author),
    service: SurveyService = Depends(get_survey_service),
) -> SurveyResponse:
    survey = await service.get(survey_id)
    return SurveyResponse.model_validate(survey)


@router.put(
    "/{survey_id}",
    response_model=SurveyResponse,
    summary="Update a survey",
    description=(
        "Declaratively replace a survey's configuration. Questions and options are "
        "reconciled by id. Restricted to the author or an admin."
    ),
    responses={
        **_AUTH_RESPONSES,
        status.HTTP_400_BAD_REQUEST: {"description": "Invalid survey structure"},
        status.HTTP_404_NOT_FOUND: {
            "description": "Survey or targeted establishment not found"
        },
        status.HTTP_409_CONFLICT: {
            "description": "Survey name already exists or survey is locked"
        },
    },
)
async def update_survey(
    survey_id: UUID,
    data: SurveyUpdateRequest,
    actor: UserActor = Depends(require_survey_author),
    service: SurveyService = Depends(get_survey_service),
) -> SurveyResponse:
    survey = await service.update(survey_id, data, actor)
    return SurveyResponse.model_validate(survey)


@router.post(
    "/{survey_id}/duplicate",
    response_model=SurveyResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Duplicate a survey",
    description="Deep-copy a survey under a unique '<name> (copy)' name.",
    responses={
        **_AUTH_RESPONSES,
        status.HTTP_404_NOT_FOUND: {"description": "Survey not found"},
        status.HTTP_409_CONFLICT: {"description": "Survey name already exists"},
    },
)
async def duplicate_survey(
    survey_id: UUID,
    actor: UserActor = Depends(require_survey_author),
    service: SurveyService = Depends(get_survey_service),
) -> SurveyResponse:
    survey = await service.duplicate(survey_id, actor)
    return SurveyResponse.model_validate(survey)


@router.delete(
    "/{survey_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a survey",
    description="Delete a survey and its questions/options. Restricted to the "
    "author or an admin.",
    responses={
        **_AUTH_RESPONSES,
        status.HTTP_404_NOT_FOUND: {"description": "Survey not found"},
        status.HTTP_409_CONFLICT: {"description": "Survey is locked"},
    },
)
async def delete_survey(
    survey_id: UUID,
    actor: UserActor = Depends(require_survey_author),
    service: SurveyService = Depends(get_survey_service),
) -> None:
    await service.delete(survey_id, actor)


@router.patch(
    "/{survey_id}/status",
    response_model=SurveyResponse,
    summary="Activate or deactivate a survey",
    description=(
        "Toggle a survey's active flag. Bypasses the edit-lock so surveys with "
        "responses can still be paused. Restricted to the author or an admin."
    ),
    responses={
        **_AUTH_RESPONSES,
        status.HTTP_404_NOT_FOUND: {"description": "Survey not found"},
    },
)
async def set_survey_status(
    survey_id: UUID,
    data: SurveyStatusRequest,
    actor: UserActor = Depends(require_survey_author),
    service: SurveyService = Depends(get_survey_service),
) -> SurveyResponse:
    survey = await service.set_active(survey_id, data.is_active, actor)
    return SurveyResponse.model_validate(survey)
