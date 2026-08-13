from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.survey_response_edit import SurveyResponseEdit
from app.utils.db import insert_with_savepoint


class SurveyResponseEditRepository:
    """Persistence operations for SurveyResponseEdit entities."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, edit_id: UUID) -> SurveyResponseEdit | None:
        """Return a survey response edit by id, or None if it does not exist."""
        return await self.db.get(SurveyResponseEdit, edit_id)

    async def create(
        self,
        *,
        id: UUID | None,
        response_id: UUID,
        edited_by_id: UUID,
        answers: dict,
        event_at: datetime,
    ) -> SurveyResponseEdit:
        """Persist a new edit-log row. ``id`` is optional; when None the server
        generates it.

        The insert runs inside a SAVEPOINT so a unique violation rolls back only
        the failed row and leaves the session usable for the caller to re-query.

        Raises:
            UniqueConstraintError: If the id is already in use. The caller is
                responsible for re-querying to decide the outcome.
        """
        fields = dict(
            response_id=response_id,
            edited_by_id=edited_by_id,
            answers=answers,
            event_at=event_at,
        )
        if id is not None:
            fields["id"] = id
        edit = SurveyResponseEdit(**fields)
        return await insert_with_savepoint(self.db, edit, "id", id)
