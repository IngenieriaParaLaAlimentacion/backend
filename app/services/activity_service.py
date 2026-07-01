from uuid import UUID

from app.core.interfaces.unit_of_work import IUnitOfWork
from app.domain.activity import ActivityItemDomain, ActivityListingParams
from app.domain.pagination import PaginatedResult
from app.domain.user import UserActor


class ActivityService:
    """Business logic for a user's own recent-activity feed."""

    def __init__(self, uow: IUnitOfWork) -> None:
        self.uow = uow

    async def get_recent_activity(
        self,
        actor: UserActor,
        page: int,
        page_size: int,
        params: ActivityListingParams,
    ) -> PaginatedResult[ActivityItemDomain]:
        """Return the caller's own subjects-created and measurements-taken,
        merged into one date-descending feed."""
        page = max(1, page)
        offset = (page - 1) * page_size
        items, total = await self.uow.activity_repo.get_activity_feed(
            actor_id=UUID(str(actor.user_id)),
            limit=page_size,
            offset=offset,
            activity_type=params.activity_type,
        )
        return PaginatedResult.build(
            items=items, total=total, page=page, page_size=page_size
        )
