from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, cast, exists, func, literal, or_, select, union_all
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain.survey_response import (
    DashboardIndicatorsParams,
    SurveyResponseListingParams,
)
from app.exceptions.domain_exceptions import UniqueConstraintError
from app.models.establishment import Establishment
from app.models.survey import Survey
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
        score_fies: int | None,
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
            score_fies=score_fies,
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
        self,
        response: SurveyResponse,
        *,
        answers: dict,
        score_fies: int | None,
        event_at: datetime,
    ) -> SurveyResponse:
        """Full-replace a response's answers and event_at."""
        response.answers = answers
        response.score_fies = score_fies
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

    @staticmethod
    def _filter_conditions(params: SurveyResponseListingParams) -> list:
        conditions = []
        if params.establishment_id is not None:
            conditions.append(
                SurveyResponse.establishment_id == params.establishment_id
            )
        if params.event_at_from is not None:
            conditions.append(SurveyResponse.event_at >= params.event_at_from)
        if params.event_at_to is not None:
            conditions.append(SurveyResponse.event_at <= params.event_at_to)
        if params.city is not None:
            conditions.append(Establishment.city.ilike(params.city))
        if params.province is not None:
            conditions.append(Establishment.province.ilike(params.province))
        return conditions

    async def list_by_survey(
        self,
        survey_id: UUID,
        *,
        limit: int,
        offset: int,
        params: SurveyResponseListingParams,
    ) -> tuple[list[SurveyResponse], int]:
        """Return a page of responses to a survey, newest event_at first, plus
        the total count matching the survey and filters.

        Joins Establishment only when city/province filters are present; the
        eager-load via selectinload still fetches the full establishment for
        every row regardless, so this join exists purely for filtering.
        """
        conditions = [SurveyResponse.survey_id == survey_id]
        needs_establishment_join = (
            params.city is not None or params.province is not None
        )
        conditions.extend(self._filter_conditions(params))

        base_query = select(SurveyResponse)
        count_query = select(func.count(SurveyResponse.id.distinct()))
        if needs_establishment_join:
            base_query = base_query.join(
                Establishment, SurveyResponse.establishment_id == Establishment.id
            )
            count_query = count_query.join(
                Establishment, SurveyResponse.establishment_id == Establishment.id
            )
        for condition in conditions:
            base_query = base_query.where(condition)
            count_query = count_query.where(condition)

        total = (await self.db.execute(count_query)).scalar_one()

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

    async def get_dashboard_indicators(
        self, params: DashboardIndicatorsParams
    ) -> tuple[int, int, datetime | None]:
        """Return (response_count, participating_establishments_count,
        last_event_at) over responses matching params — every filter optional,
        unlike list_by_survey where survey_id is fixed by the caller."""
        conditions = []
        if params.survey_id is not None:
            conditions.append(SurveyResponse.survey_id == params.survey_id)
        if params.establishment_id is not None:
            conditions.append(
                SurveyResponse.establishment_id == params.establishment_id
            )
        if params.event_at_from is not None:
            conditions.append(SurveyResponse.event_at >= params.event_at_from)
        if params.event_at_to is not None:
            conditions.append(SurveyResponse.event_at <= params.event_at_to)
        if params.city is not None:
            conditions.append(Establishment.city.ilike(params.city))
        if params.province is not None:
            conditions.append(Establishment.province.ilike(params.province))

        needs_establishment_join = (
            params.city is not None or params.province is not None
        )
        query = select(
            func.count(SurveyResponse.id),
            func.count(SurveyResponse.establishment_id.distinct()),
            func.max(SurveyResponse.event_at),
        )
        if needs_establishment_join:
            query = query.join(
                Establishment, SurveyResponse.establishment_id == Establishment.id
            )
        for condition in conditions:
            query = query.where(condition)

        result = await self.db.execute(query)
        response_count, establishments_count, last_event_at = result.one()
        return response_count, establishments_count, last_event_at

    async def list_all_for_export(
        self, survey_id: UUID, establishment_id: UUID
    ) -> list[SurveyResponse]:
        """Return every response to a survey at one establishment, with
        survey.questions(.options), establishment and submitted_by
        eager-loaded — for  export, which needs every matching response's
        full detail in one pass, not a paginated page.
        """
        query = (
            select(SurveyResponse)
            .where(
                SurveyResponse.survey_id == survey_id,
                SurveyResponse.establishment_id == establishment_id,
            )
            .options(
                selectinload(SurveyResponse.survey).selectinload(Survey.questions),
                selectinload(SurveyResponse.establishment),
                selectinload(SurveyResponse.submitted_by),
            )
            .order_by(SurveyResponse.event_at.desc())
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())
