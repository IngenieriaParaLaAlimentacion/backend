from fastapi import APIRouter, Depends, status

from app.api.v1.params import AUTH_RESPONSES, SurveyResponseSummaryQuery
from app.core.dependencies import (
    get_analytics_service,
    require_admin_or_analyst,
)
from app.domain import UserActor
from app.schemas.analytics_schema import SurveyResponseSummaryResponse
from app.services.analytics_service import AnalyticsService

router = APIRouter(prefix="/analytics")


@router.get(
    "/survey-response-summary",
    response_model=SurveyResponseSummaryResponse,
    summary="Survey response summary metrics",
    description=(
        "Returns aggregate statistics across survey responses: total submissions, "
        "number of distinct establishments that submitted responses, and the date "
        "of the last submission. All filters are optional — omit them to get "
        "platform-wide figures. Restricted to admin, analyst, and superadmin roles."
    ),
    responses={
        **AUTH_RESPONSES,
        status.HTTP_400_BAD_REQUEST: {"description": "Invalid filter range"},
    },
)
async def get_survey_response_summary(
    query: SurveyResponseSummaryQuery = Depends(),
    actor: UserActor = Depends(require_admin_or_analyst),
    service: AnalyticsService = Depends(get_analytics_service),
) -> SurveyResponseSummaryResponse:
    query.validate()
    summary = await service.get_survey_response_summary(actor, query.to_domain())
    return SurveyResponseSummaryResponse.model_validate(summary)
