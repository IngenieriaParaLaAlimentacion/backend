from uuid import UUID

from fastapi import APIRouter, Depends, Response, status

from app.api.v1.params import (
    AUTH_RESPONSES,
    PaginatedQueryParams,
    SurveyResponseListingQuery,
)
from app.core.dependencies import get_survey_response_service, require_some
from app.domain import UserActor
from app.domain.user import UserRole
from app.schemas.pagination import PaginatedResponse
from app.schemas.survey_response_schema import (
    SurveyResponseDashboardItem,
    SurveyResponseDetailResponse,
    SurveyResponseEditRequest,
    SurveyResponseRequest,
    SurveyResponseResponse,
)
from app.services.exporters.factory import ExportFormat, get_exporter
from app.services.survey_response_service import SurveyResponseService

router = APIRouter(prefix="/survey-responses")

_submitter_or_editor = require_some(
    UserRole.FIELD_WORKER, UserRole.ADMIN, UserRole.SUPERADMIN
)

_dashboard_reader = require_some(UserRole.ADMIN, UserRole.ANALYST, UserRole.SUPERADMIN)


@router.get(
    "/export",
    summary="Export a survey's responses at one establishment",
    description=(
        "Export every response to a survey at one establishment into a "
        "downloadable file including both response data and a visual "
        "summary of indicators. Restricted to admins, analysts and "
        "superadmins (dashboard use)."
    ),
    responses={
        **AUTH_RESPONSES,
        status.HTTP_404_NOT_FOUND: {"description": "Survey not found"},
    },
)
async def export_survey_responses(
    survey_id: UUID,
    establishment_id: UUID,
    format: ExportFormat = ExportFormat.XLSX,
    actor: UserActor = Depends(_dashboard_reader),
    service: SurveyResponseService = Depends(get_survey_response_service),
) -> Response:
    exporter = get_exporter(format)
    file_bytes = await service.export(survey_id, establishment_id, actor, exporter)
    return Response(
        content=file_bytes,
        media_type=exporter.content_type,
        headers={
            "Content-Disposition": f'attachment; \
                filename="export.{exporter.file_extension}"'
        },
    )


@router.get(
    "/{response_id}",
    response_model=SurveyResponseResponse,
    summary="Get a survey response",
    description=(
        "Return a response's full detail, including its answers. Restricted to "
        "the original submitter or an admin/superadmin — the same actors allowed "
        "to edit it."
    ),
    responses={
        **AUTH_RESPONSES,
        status.HTTP_404_NOT_FOUND: {"description": "Response not found"},
    },
)
async def get_survey_response(
    response_id: UUID,
    actor: UserActor = Depends(_submitter_or_editor),
    service: SurveyResponseService = Depends(get_survey_response_service),
) -> SurveyResponseResponse:
    survey_response = await service.get(response_id, actor)
    return SurveyResponseResponse.model_validate(survey_response)


@router.get(
    "",
    response_model=PaginatedResponse[SurveyResponseDashboardItem],
    summary="List responses to a survey",
    description=(
        "Paginated, filterable list of a survey's responses, newest event_at "
        "first, each showing who submitted it, the establishment, and the "
        "survey date. Filter by establishment, event date range, and/or the "
        "establishment's city/province. Restricted to admins, analysts and "
        "superadmins (dashboard use)."
    ),
    responses={
        **AUTH_RESPONSES,
        status.HTTP_400_BAD_REQUEST: {"description": "Invalid filter range"},
        status.HTTP_404_NOT_FOUND: {"description": "Survey not found"},
    },
)
async def list_survey_responses(
    survey_id: UUID,
    query: SurveyResponseListingQuery = Depends(),
    paginated: PaginatedQueryParams = Depends(),
    actor: UserActor = Depends(_dashboard_reader),
    service: SurveyResponseService = Depends(get_survey_response_service),
) -> PaginatedResponse[SurveyResponseDashboardItem]:
    query.validate()
    result = await service.list_by_survey(
        survey_id,
        actor,
        page=paginated.page,
        page_size=paginated.page_size,
        params=query.to_domain(),
    )
    return PaginatedResponse[SurveyResponseDashboardItem](
        items=[SurveyResponseDashboardItem.model_validate(r) for r in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
        total_pages=result.total_pages,
    )


@router.post(
    "",
    response_model=SurveyResponseResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a survey response",
    description=(
        "Idempotent, offline-first submission of one anonymous individual's "
        "answers to a survey at an establishment. Replaying the same id returns the "
        "stored record unchanged. No draft mode: required questions must all "
        "be answered or the submission is rejected outright."
    ),
    responses={
        status.HTTP_200_OK: {
            "description": "Response already existed; idempotent replay of the same id."
        },
        **AUTH_RESPONSES,
        status.HTTP_400_BAD_REQUEST: {
            "description": "Answers invalid, or establishment outside the "
            "survey's audience"
        },
        status.HTTP_404_NOT_FOUND: {"description": "Survey or establishment not found"},
    },
)
async def submit_survey_response(
    data: SurveyResponseRequest,
    response: Response,
    actor: UserActor = Depends(_submitter_or_editor),
    service: SurveyResponseService = Depends(get_survey_response_service),
) -> SurveyResponseResponse:
    survey_response, created = await service.submit(data, actor)
    if not created:
        response.status_code = status.HTTP_200_OK
    return SurveyResponseResponse.model_validate(survey_response)


@router.put(
    "/{response_id}",
    response_model=SurveyResponseResponse,
    summary="Edit a survey response",
    description=(
        "Full-replace edit of a response's answers. Restricted to the "
        "original submitter or an admin/superadmin. Idempotent per edit "
        "attempt id for offline-first retries."
    ),
    responses={
        **AUTH_RESPONSES,
        status.HTTP_400_BAD_REQUEST: {"description": "Answers invalid"},
        status.HTTP_404_NOT_FOUND: {"description": "Response not found"},
    },
)
async def edit_survey_response(
    response_id: UUID,
    data: SurveyResponseEditRequest,
    actor: UserActor = Depends(_submitter_or_editor),
    service: SurveyResponseService = Depends(get_survey_response_service),
) -> SurveyResponseResponse:
    survey_response = await service.edit(response_id, data, actor)
    return SurveyResponseResponse.model_validate(survey_response)


@router.get(
    "/{response_id}/dashboard-detail",
    response_model=SurveyResponseDetailResponse,
    summary="Get full response detail for the dashboard",
    description=(
        "Return one user's full response detail: every question in the survey "
        "and the value that user registered for it, with choice answers "
        "resolved to option text. Restricted to admins, analysts and "
        "superadmins (dashboard use — no ownership check, unlike "
        "GET /survey-responses/{id})."
    ),
    responses={
        **AUTH_RESPONSES,
        status.HTTP_404_NOT_FOUND: {"description": "Response not found"},
    },
)
async def get_survey_response_dashboard_detail(
    response_id: UUID,
    actor: UserActor = Depends(_dashboard_reader),
    service: SurveyResponseService = Depends(get_survey_response_service),
) -> SurveyResponseDetailResponse:
    detail = await service.get_response_detail(response_id, actor)
    return SurveyResponseDetailResponse.model_validate(detail)
