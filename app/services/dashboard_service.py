from app.core.interfaces.unit_of_work import IUnitOfWork
from app.domain.survey_response import (
    DashboardIndicatorsDomain,
    DashboardIndicatorsParams,
)
from app.domain.user import UserActor, UserRole
from app.exceptions.domain_exceptions import ForbiddenError

_DASHBOARD_ROLES = {UserRole.ADMIN, UserRole.ANALYST, UserRole.SUPERADMIN}


class DashboardService:
    """Business logic for the dashboard's general indicators panel (CA4)."""

    def __init__(self, uow: IUnitOfWork) -> None:
        self.uow = uow

    async def get_indicators(
        self, actor: UserActor, params: DashboardIndicatorsParams
    ) -> DashboardIndicatorsDomain:
        """Return the dashboard's general indicators over responses matching
        params: total responses, distinct participating establishments, and
        the most recent event_at.

        Raises:
            ForbiddenError: actor role isn't a dashboard reader.
        """
        if actor.role not in _DASHBOARD_ROLES:
            raise ForbiddenError()
        (
            response_count,
            establishments_count,
            last_event_at,
        ) = await self.uow.survey_response_repo.get_dashboard_indicators(params)
        return DashboardIndicatorsDomain(
            response_count=response_count,
            participating_establishments_count=establishments_count,
            last_event_at=last_event_at,
        )
