from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, cast, exists, func, literal, or_, select, union_all
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.exceptions.domain_exceptions import UniqueConstraintError
from app.models.survey import Survey
from app.models.survey_response import SurveyResponse


class SurveyResponseRepository:
    """Persistence operations for SurveyResponse entities."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, response_id: UUID) -> SurveyResponse | None:
        """Return a survey response by id, or None if it does not exist."""
        return await self.db.get(SurveyResponse, response_id)

    async def list_by_survey(
        self, survey_id: UUID, *, limit: int, offset: int
    ) -> tuple[list[SurveyResponse], int]:
        """Return a page of responses to a survey, newest event_at first, plus
        the total count matching the survey (ignoring pagination).

        Eager-loads survey, establishment and submitted_by so the dashboard
        list can serialize without triggering lazy-load N+1 queries.
        """
        base_query = select(SurveyResponse).where(SurveyResponse.survey_id == survey_id)

        total = (
            await self.db.execute(
                select(func.count()).select_from(base_query.subquery())
            )
        ).scalar_one()

        rows_query = (
            base_query.options(
                selectinload(SurveyResponse.survey),
                selectinload(SurveyResponse.establishment),
                selectinload(SurveyResponse.submitted_by),
            )
            .order_by(SurveyResponse.event_at.desc())
            .limit(limit)
            .offset(offset)
        )
        rows = (await self.db.execute(rows_query)).scalars().all()
        return list(rows), total

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

    async def get_referenced_option_ids(
        self, survey_id: UUID, question_option_pairs: list[tuple[UUID, UUID]]
    ) -> set[UUID]:
        """Return the subset of ``(question_id, option_id)`` pairs where some
        response to ``survey_id`` selected that option — either as a
        SINGLE_CHOICE scalar value or inside a MULTIPLE_CHOICE list.
        """
        if not question_option_pairs:
            return set()

        per_option_selects = []
        for question_id, option_id in question_option_pairs:
            answer = SurveyResponse.answers[str(question_id)]
            option_str = str(option_id)
            condition = and_(
                SurveyResponse.survey_id == survey_id,
                or_(
                    answer.astext == option_str,
                    answer.contains(cast([option_str], JSONB)),
                ),
            )
            per_option_selects.append(
                select(literal(option_str)).where(exists().where(condition))
            )

        result = await self.db.execute(union_all(*per_option_selects))
        return {UUID(value) for value in result.scalars().all()}

    async def get_with_relations(self, response_id: UUID) -> SurveyResponse | None:
        """Return a response by id with survey.questions (each question's
        options load automatically via SurveyQuestion.options' own
        lazy="selectin"), establishment and submitted_by eager-loaded — for
        the dashboard detail view, which needs question text and option
        labels alongside each answer.
        """
        query = (
            select(SurveyResponse)
            .where(SurveyResponse.id == response_id)
            .options(
                selectinload(SurveyResponse.survey).selectinload(Survey.questions),
                selectinload(SurveyResponse.establishment),
                selectinload(SurveyResponse.submitted_by),
            )
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()
