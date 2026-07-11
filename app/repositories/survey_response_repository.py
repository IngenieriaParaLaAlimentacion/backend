from datetime import datetime
from uuid import UUID

from sqlalchemy import cast, exists, or_, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions.domain_exceptions import UniqueConstraintError
from app.models.survey_response import SurveyResponse


class SurveyResponseRepository:
    """Persistence operations for SurveyResponse entities."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, response_id: UUID) -> SurveyResponse | None:
        """Return a survey response by id, or None if it does not exist."""
        return await self.db.get(SurveyResponse, response_id)

    async def create(
        self,
        *,
        id: UUID | None,
        survey_id: UUID,
        establishment_id: UUID,
        submitted_by_id: UUID,
        answers: dict,
        event_at: datetime,
    ) -> SurveyResponse:
        """Persist a new response. ``id`` is optional; when None the server
        generates it.

        The insert runs inside a SAVEPOINT so a unique violation rolls back only
        the failed row and leaves the session usable for the caller to re-query.

        Raises:
            UniqueConstraintError: If the id is already in use. The caller is
                responsible for re-querying to decide the outcome.
        """
        fields = dict(
            survey_id=survey_id,
            establishment_id=establishment_id,
            submitted_by_id=submitted_by_id,
            answers=answers,
            event_at=event_at,
        )
        if id is not None:
            fields["id"] = id
        response = SurveyResponse(**fields)
        try:
            async with self.db.begin_nested():
                self.db.add(response)
                await self.db.flush()
        except IntegrityError:
            raise UniqueConstraintError("id", id)
        await self.db.refresh(response)
        return response

    async def update_answers(
        self, response: SurveyResponse, *, answers: dict, event_at: datetime
    ) -> SurveyResponse:
        """Full-replace a response's answers and event_at."""
        response.answers = answers
        response.event_at = event_at
        await self.db.flush()
        await self.db.refresh(response, attribute_names=["updated_at"])
        return response

    async def is_option_referenced(
        self, survey_id: UUID, question_id: UUID, option_id: UUID
    ) -> bool:
        """Return True if any response to ``survey_id`` selected ``option_id``
        for ``question_id`` — either as a SINGLE_CHOICE scalar value or inside
        a MULTIPLE_CHOICE list."""
        answer = SurveyResponse.answers[str(question_id)]
        option_str = str(option_id)
        condition = or_(
            answer.astext == option_str,
            answer.contains(cast([option_str], JSONB)),
        )
        result = await self.db.execute(
            select(exists().where(SurveyResponse.survey_id == survey_id, condition))
        )
        return bool(result.scalar())
