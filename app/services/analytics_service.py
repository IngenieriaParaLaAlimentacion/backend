from app.core.interfaces.unit_of_work import IUnitOfWork
from app.domain.survey_response import (
    SurveyResponseSummaryDomain,
    SurveyResponseSummaryParams,
)
from app.domain.user import UserActor, UserRole
from app.exceptions.domain_exceptions import ForbiddenError

_ANALYTICS_ROLES = {UserRole.ADMIN, UserRole.ANALYST, UserRole.SUPERADMIN}


class AnalyticsService:
    """Business logic for cross-module analytics (CA4)."""

    def __init__(self, uow: IUnitOfWork) -> None:
        self.uow = uow

    async def get_survey_response_summary(
        self, actor: UserActor, params: SurveyResponseSummaryParams
    ) -> SurveyResponseSummaryDomain:
        """Return aggregated metrics over survey responses matching
        params: total responses, distinct participating establishments, and
        the most recent event_at.

        Raises:
            ForbiddenError: actor role isn't allowed to view analytics.
        """
        if actor.role not in _ANALYTICS_ROLES:
            raise ForbiddenError()
        (
            response_count,
            establishments_count,
            last_event_at,
        ) = await self.uow.survey_response_repo.get_survey_response_summary(params)
        return SurveyResponseSummaryDomain(
            response_count=response_count,
            participating_establishments_count=establishments_count,
            last_event_at=last_event_at,
        )
