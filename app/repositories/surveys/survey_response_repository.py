from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_, cast, exists, func, literal, or_, select, union_all
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain.survey_response import (
    SurveyResponseListingParams,
    SurveyResponseSummaryParams,
)
from app.exceptions.domain_exceptions import UniqueConstraintError
from app.models.establishments.establishment import Establishment
from app.models.surveys.survey import Survey
from app.models.surveys.survey_response import SurveyResponse

_CONSTRAINT_FIELDS = {
    "uq_survey_responses_survey_establishment": "establishment_id",
    "uq_survey_responses_survey_subject": "subject_id",
}


def _violated_constraint(error: IntegrityError) -> str | None:
    """Return the name of the constraint Postgres rejected the write on.

    asyncpg carries it on the ``UniqueViolationError`` at ``orig.__cause__``,
    psycopg2 under ``orig.diag``.
    """
    for candidate in (error.orig, getattr(error.orig, "__cause__", None)):
        if candidate is None:
            continue
        name = getattr(candidate, "constraint_name", None) or getattr(
            getattr(candidate, "diag", None), "constraint_name", None
        )
        if name:
            return name
    return None


class SurveyResponseRepository:
    """Persistence operations for SurveyResponse entities."""

    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def _full_relations_options() -> tuple:
        """Common eager-loading options for detail and export views."""
        return (
            selectinload(SurveyResponse.survey).selectinload(Survey.questions),
            selectinload(SurveyResponse.establishment),
            selectinload(SurveyResponse.subject),
            selectinload(SurveyResponse.submitted_by),
        )

    @staticmethod
    def _apply_filters(
        query: Any,
        params: SurveyResponseListingParams | SurveyResponseSummaryParams,
        survey_id: UUID | None = None,
    ) -> Any:
        """Applies common filters and conditional joins to a SQLAlchemy query."""
        target_survey_id = survey_id or getattr(params, "survey_id", None)
        conditions = []

        if target_survey_id:
            conditions.append(SurveyResponse.survey_id == target_survey_id)
        if params.establishment_id:
            conditions.append(
                SurveyResponse.establishment_id == params.establishment_id
            )
        if params.event_at_from:
            conditions.append(SurveyResponse.event_at >= params.event_at_from)
        if params.event_at_to:
            conditions.append(SurveyResponse.event_at <= params.event_at_to)

        # Dynamic join based on location filters
        if params.city or params.province:
            query = query.join(
                Establishment, SurveyResponse.establishment_id == Establishment.id
            )
            if params.city:
                conditions.append(Establishment.city.ilike(params.city))
            if params.province:
                conditions.append(Establishment.province.ilike(params.province))

        if conditions:
            query = query.where(and_(*conditions))

        return query

    async def get_by_id(self, response_id: UUID) -> SurveyResponse | None:
        """Return a survey response by id, or None if it does not exist."""
        return await self.db.get(SurveyResponse, response_id)

    async def create(
        self,
        *,
        id: UUID | None,
        survey_id: UUID,
        subject_id: UUID | None,
        establishment_id: UUID | None,
        submitted_by_id: UUID,
        answers: dict,
        score_fies: int | None,
        event_at: datetime,
    ) -> SurveyResponse:
        """Persist a new response inside a SAVEPOINT.

        Raises:
            UniqueConstraintError: ``field`` names what collided — ``id`` for a
                replayed primary key, ``subject_id`` / ``establishment_id`` when
                the target already answered this survey.
        """
        fields = dict(
            survey_id=survey_id,
            subject_id=subject_id,
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
        except IntegrityError as error:
            field = _CONSTRAINT_FIELDS.get(_violated_constraint(error), "id")
            raise UniqueConstraintError(field, fields.get(field, id))

        await self.db.refresh(response)
        return response

    async def get_by_target(
        self,
        survey_id: UUID,
        *,
        subject_id: UUID | None,
        establishment_id: UUID | None,
    ) -> SurveyResponse | None:
        """Return the response already recorded for this survey's target, if any.

        An anonymous response has no target, so None is returned without querying.
        """
        conditions = [SurveyResponse.survey_id == survey_id]
        if subject_id is not None:
            conditions.append(SurveyResponse.subject_id == subject_id)
        elif establishment_id is not None:
            conditions.append(SurveyResponse.establishment_id == establishment_id)
        else:
            return None

        query = (
            select(SurveyResponse)
            .where(*conditions)
            .options(selectinload(SurveyResponse.submitted_by))
        )
        return (await self.db.execute(query)).scalar_one_or_none()

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

    async def get_with_relations(self, response_id: UUID) -> SurveyResponse | None:
        """Return a response by id with full relations eager-loaded."""
        query = (
            select(SurveyResponse)
            .where(SurveyResponse.id == response_id)
            .options(*self._full_relations_options())
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def list_all_for_export(
        self, survey_id: UUID, establishment_id: UUID | None = None
    ) -> list[SurveyResponse]:
        """Return every response to a survey with relations.

        Optionally filter by establishment.
        """
        conditions = [SurveyResponse.survey_id == survey_id]
        if establishment_id is not None:
            conditions.append(SurveyResponse.establishment_id == establishment_id)

        query = (
            select(SurveyResponse)
            .where(*conditions)
            .options(*self._full_relations_options())
            .order_by(SurveyResponse.event_at.desc())
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def list_by_survey(
        self,
        survey_id: UUID,
        *,
        limit: int,
        offset: int,
        params: SurveyResponseListingParams,
    ) -> tuple[list[SurveyResponse], int]:
        """Return a paginated list of responses to a survey plus total count."""
        count_query = self._apply_filters(
            select(func.count(SurveyResponse.id.distinct())),
            params,
            survey_id=survey_id,
        )
        total = (await self.db.execute(count_query)).scalar_one()

        rows_query = self._apply_filters(
            select(SurveyResponse), params, survey_id=survey_id
        )
        rows_query = (
            rows_query.options(
                selectinload(SurveyResponse.survey),
                selectinload(SurveyResponse.establishment),
                selectinload(SurveyResponse.subject),
                selectinload(SurveyResponse.submitted_by),
            )
            .order_by(SurveyResponse.event_at.desc())
            .limit(limit)
            .offset(offset)
        )
        rows = (await self.db.execute(rows_query)).scalars().all()

        return list(rows), total

    async def get_survey_response_summary(
        self, params: SurveyResponseSummaryParams
    ) -> tuple[int, int, datetime | None]:
        """Return aggregated metrics (response_count, establishments_count,
        last_event_at)."""
        base_query = select(
            func.count(SurveyResponse.id),
            func.count(SurveyResponse.establishment_id.distinct()),
            func.max(SurveyResponse.event_at),
        )
        query = self._apply_filters(base_query, params)
        result = await self.db.execute(query)
        return result.one()

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
