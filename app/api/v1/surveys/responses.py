from uuid import UUID

from fastapi import APIRouter, Depends, Response, status

from app.api.v1.params import (
    AUTH_RESPONSES,
    PaginatedQueryParams,
    SurveyResponseListingQuery,
)
from app.core.dependencies import (
    get_survey_response_service,
    require_admin_or_analyst,
    require_any,
)
from app.domain import UserActor
from app.schemas.pagination import PaginatedResponse
from app.schemas.surveys.survey_response_schema import (
    SurveyResponseDashboardItem,
    SurveyResponseDetailResponse,
    SurveyResponseEditRequest,
    SurveyResponseRequest,
    SurveyResponseResponse,
)
from app.services.exporters.factory import ExportFormat, get_exporter
from app.services.surveys.survey_response_service import SurveyResponseService

router = APIRouter(prefix="/surveys/{survey_id}/responses")


@router.get(
    "/export",
    summary="Export a survey's responses (accepts the listing's filters)",
    description=(
        "Export responses to a survey into a downloadable file including "
        "both response data and a visual summary of indicators. The first "
        "column is the response number the field worker entered. A survey "
        "targeted at subjects also exports each respondent's name, last name "
        "and DNI. Accepts exactly the same filters as the listing. Restricted "
        "to admins, analysts and superadmins."
    ),
    responses={
        **AUTH_RESPONSES,
        status.HTTP_200_OK: {
            "description": "Survey responses exported successfully",
            "content": {
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {}
            },
        },
        status.HTTP_400_BAD_REQUEST: {
            "description": "`/errors/filter-not-applicable`: a target filter was "
            "applied to a survey that does not carry that target. "
            "`/errors/invalid-date-range`: event_at_from is after event_at_to. "
            "`/errors/invalid-response-number-range`: response_number_from is "
            "greater than response_number_to."
        },
        status.HTTP_404_NOT_FOUND: {"description": "Survey not found"},
    },
)
async def export_survey_responses(
    survey_id: UUID,
    query: SurveyResponseListingQuery = Depends(),
    format: ExportFormat = ExportFormat.XLSX,
    actor: UserActor = Depends(require_admin_or_analyst),
    service: SurveyResponseService = Depends(get_survey_response_service),
) -> Response:
    query.validate()
    exporter = get_exporter(format)
    file_bytes = await service.export(survey_id, actor, exporter, query.to_domain())
    return Response(
        content=file_bytes,
        media_type=exporter.content_type,
        headers={
            "Content-Disposition": (
                f'attachment; filename="export.{exporter.file_extension}"'
            )
        },
    )


@router.get(
    "",
    response_model=PaginatedResponse[SurveyResponseDashboardItem],
    summary="List responses to a survey",
    description=(
        "Paginated, filterable and sortable list of a survey's responses, "
        "newest event_at first by default, each showing who submitted it, the "
        "subject or establishment it is about, and the survey date. Filter by "
        "event date range, and by whichever target the survey carries: "
        "`subject_id` when `response_target` is `subject`, or "
        "`establishment_id` and the establishment's city/province when it is "
        "`establishment`. A filter that resolves through a target the survey "
        "does not carry is rejected. Also filterable by response number, "
        "exactly or by range. Restricted to admins, analysts and "
        "superadmins."
    ),
    responses={
        **AUTH_RESPONSES,
        status.HTTP_400_BAD_REQUEST: {
            "description": "`/errors/invalid-date-range`: event_at_from is after "
            "event_at_to. `/errors/invalid-response-number-range`: "
            "response_number_from is greater than response_number_to. "
            "`/errors/filter-not-applicable`: a target filter was "
            "applied to a survey that does not carry that target."
        },
        status.HTTP_404_NOT_FOUND: {"description": "Survey not found"},
    },
)
async def list_survey_responses(
    survey_id: UUID,
    query: SurveyResponseListingQuery = Depends(),
    paginated: PaginatedQueryParams = Depends(),
    actor: UserActor = Depends(require_admin_or_analyst),
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
        "Idempotent, offline-first submission of answers to a survey. The body "
        "must carry `subject_id` or `establishment_id` to match the survey's "
        "`response_target`, and neither when it is anonymous. Replaying the same "
        "id returns the stored record unchanged — the id is checked before the "
        "one-response-per-target rule, so a retried sync never reports a "
        "conflict against itself. `response_number` is required on every survey "
        "but may be shared by multiple responses. No draft mode: required "
        "questions must all be answered or the submission is rejected outright."
    ),
    responses={
        status.HTTP_200_OK: {
            "description": "Response already existed; idempotent replay of the same id."
        },
        **AUTH_RESPONSES,
        status.HTTP_400_BAD_REQUEST: {
            "description": "Answers invalid, or the payload does not match the "
            "survey's response target"
        },
        status.HTTP_404_NOT_FOUND: {
            "description": "Survey, establishment or subject not found"
        },
        status.HTTP_409_CONFLICT: {
            "description": "This subject or establishment already answered this survey."
        },
    },
)
async def submit_survey_response(
    survey_id: UUID,
    data: SurveyResponseRequest,
    response: Response,
    actor: UserActor = Depends(require_any),
    service: SurveyResponseService = Depends(get_survey_response_service),
) -> SurveyResponseResponse:
    survey_response, created = await service.submit(survey_id, data, actor)
    if not created:
        response.status_code = status.HTTP_200_OK
    return SurveyResponseResponse.model_validate(survey_response)


@router.get(
    "/{response_id}",
    response_model=SurveyResponseResponse,
    summary="Get a survey response (Standard)",
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
    actor: UserActor = Depends(require_any),
    service: SurveyResponseService = Depends(get_survey_response_service),
) -> SurveyResponseResponse:
    survey_response = await service.get(response_id, actor)
    return SurveyResponseResponse.model_validate(survey_response)


@router.get(
    "/{response_id}/detail",
    response_model=SurveyResponseDetailResponse,
    summary="Get a survey response with full detail",
    description=(
        "Return one response with every question in the survey and the value "
        "that was registered, with choice answers resolved to option text. "
        "Includes who submitted it, the establishment, and the survey reference. "
        "Restricted to admins, analysts and superadmins."
    ),
    responses={
        **AUTH_RESPONSES,
        status.HTTP_404_NOT_FOUND: {"description": "Response not found"},
    },
)
async def get_survey_response_detail(
    response_id: UUID,
    actor: UserActor = Depends(require_any),
    service: SurveyResponseService = Depends(get_survey_response_service),
) -> SurveyResponseDetailResponse:
    detail = await service.get_response_detail(response_id, actor)
    return SurveyResponseDetailResponse.model_validate(detail)


@router.put(
    "/{response_id}",
    response_model=SurveyResponseResponse,
    summary="Edit a survey response",
    description=(
        "Full-replace edit of a response's answers and response number. "
        "Restricted to the original submitter or an admin/superadmin. "
        "Idempotent per edit attempt id for offline-first retries."
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
    actor: UserActor = Depends(require_any),
    service: SurveyResponseService = Depends(get_survey_response_service),
) -> SurveyResponseResponse:
    survey_response = await service.edit(response_id, data, actor)
    return SurveyResponseResponse.model_validate(survey_response)
