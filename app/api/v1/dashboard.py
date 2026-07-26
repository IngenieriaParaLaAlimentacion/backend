from fastapi import APIRouter, Depends, status

from app.api.v1.params import AUTH_RESPONSES, DashboardIndicatorsQuery
from app.core.dependencies import get_dashboard_service, require_some
from app.domain import UserActor
from app.domain.user import UserRole
from app.schemas.dashboard_schema import DashboardIndicatorsResponse
from app.services.dashboard_service import DashboardService

router = APIRouter(prefix="/dashboard")

_dashboard_reader = require_some(UserRole.ADMIN, UserRole.ANALYST, UserRole.SUPERADMIN)


@router.get(
    "/indicators",
    response_model=DashboardIndicatorsResponse,
    summary="Get the dashboard's general indicators",
    description=(
        "Return the total response count, distinct participating "
        "establishments, and the most recent event_at across responses — "
        "every filter (survey, establishment, event date range, "
        "city/province) is optional. Restricted to admins, analysts and "
        "superadmins."
    ),
    responses={
        **AUTH_RESPONSES,
        status.HTTP_400_BAD_REQUEST: {"description": "Invalid filter range"},
    },
)
async def get_dashboard_indicators(
    query: DashboardIndicatorsQuery = Depends(),
    actor: UserActor = Depends(_dashboard_reader),
    service: DashboardService = Depends(get_dashboard_service),
) -> DashboardIndicatorsResponse:
    query.validate()
    indicators = await service.get_indicators(actor, query.to_domain())
    return DashboardIndicatorsResponse.model_validate(indicators)
