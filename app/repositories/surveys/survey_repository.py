from __future__ import annotations

from uuid import UUID

from sqlalchemy import desc, exists, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import noload

from app.domain.survey import (
    QuestionInputData,
    SurveyListingParams,
    SurveyResponseTarget,
)
from app.exceptions.domain_exceptions import (
    InvalidSurveyPayloadError,
    UniqueConstraintError,
)
from app.models.surveys.survey import Survey
from app.models.surveys.survey_question import SurveyQuestion
from app.models.surveys.survey_question_option import SurveyQuestionOption
from app.repositories.surveys.constants import SURVEY_SORT_CLAUSES
from app.utils.db import execute_all_rows, execute_paginated_rows, ilike_condition


class SurveyRepository:
    """Persistence for the survey aggregate (survey + questions + options).

    The ``questions``/``options`` relationships are eager-loaded via
    ``lazy="selectin"``, so a survey fetched here carries its full configuration.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, survey_id: UUID) -> Survey | None:
        """Return a survey with its questions, options and audience, or None."""
        return await self.db.get(Survey, survey_id)

    async def name_exists(self, name: str, exclude_id: UUID | None = None) -> bool:
        """Return True if another survey already uses ``name`` (case-insensitive).

        ``exclude_id`` lets a rename ignore the survey being edited.
        """
        conditions = [func.lower(Survey.name) == name.strip().lower()]
        if exclude_id is not None:
            conditions.append(Survey.id != exclude_id)
        result = await self.db.execute(select(exists().where(*conditions)))
        return bool(result.scalar())

    @staticmethod
    def _question_count_subquery():
        """Scalar subquery: number of questions belonging to the correlated survey."""
        return (
            select(func.count(SurveyQuestion.id))
            .where(SurveyQuestion.survey_id == Survey.id)
            .correlate(Survey)
            .scalar_subquery()
        )

    @classmethod
    def _listing_base_query(cls):
        """Build the listing's ``(survey, question_count)`` query.

        The summary view needs only a question count, so ``questions`` is
        suppressed with ``noload`` and the count comes from a correlated
        subquery — avoiding hydrating every question/option just to call
        ``len()``.
        """
        question_count = cls._question_count_subquery()
        return select(Survey, question_count.label("question_count")).options(
            noload(Survey.questions)
        )

    @staticmethod
    def _listing_conditions(params: SurveyListingParams) -> list:
        """Build the filter conditions for a survey listing."""
        conditions = []
        if params.search:
            conditions.append(ilike_condition(Survey.name, params.search))
        if params.created_by is not None:
            conditions.append(Survey.created_by_id == params.created_by)
        if params.response_target is not None:
            conditions.append(Survey.response_target == params.response_target)
        if params.is_active is not None:
            conditions.append(Survey.is_active == params.is_active)
        return conditions

    @staticmethod
    def _build_question(
        q: QuestionInputData | SurveyQuestion, position: int
    ) -> SurveyQuestion:
        return SurveyQuestion(
            text=q.text,
            response_type=q.response_type,
            is_required=q.is_required,
            position=position,
            options=[
                SurveyQuestionOption(text=o.text, position=i)
                for i, o in enumerate(q.options)
            ],
        )

    def _reconcile_questions(
        self, survey: Survey, questions: list[QuestionInputData]
    ) -> None:
        existing = {q.id: q for q in survey.questions}
        for q in questions:
            if q.id is not None and q.id not in existing:
                raise InvalidSurveyPayloadError(
                    f"Question {q.id} does not belong to this survey."
                )
        new_questions = []
        for position, q in enumerate(questions):
            if q.id is not None:
                question = existing[q.id]
                question.text = q.text
                question.response_type = q.response_type
                question.is_required = q.is_required
                question.position = position
                self._reconcile_options(question, q.options)
            else:
                question = self._build_question(q, position)
            new_questions.append(question)
        # Reassigning the collection deletes orphaned questions via delete-orphan.
        survey.questions = new_questions

    @staticmethod
    def _reconcile_options(question: SurveyQuestion, options) -> None:
        existing = {o.id: o for o in question.options}
        for o in options:
            if o.id is not None and o.id not in existing:
                raise InvalidSurveyPayloadError(
                    f"Option {o.id} does not belong to question {question.id}."
                )
        new_options = []
        for position, o in enumerate(options):
            if o.id is not None:
                option = existing[o.id]
                option.text = o.text
                option.position = position
            else:
                option = SurveyQuestionOption(text=o.text, position=position)
            new_options.append(option)
        # Reassigning the collection deletes orphaned options via delete-orphan.
        question.options = new_options

    async def _flush_aggregate(self, survey: Survey, name: str) -> None:
        try:
            async with self.db.begin_nested():
                self.db.add(survey)
                await self.db.flush()
        except IntegrityError:
            raise UniqueConstraintError("name", name)
        await self._refresh_updated_at(survey)

    async def _refresh_updated_at(self, survey: Survey) -> None:
        """Reload the server-side ``updated_at`` within the async context.

        ``updated_at`` uses ``onupdate=func.now()``; after an UPDATE SQLAlchemy
        expires it, so building the domain object post-commit would otherwise
        trigger a lazy (sync) reload and raise ``MissingGreenlet``. Scoped to this
        one column so the eager-loaded questions stay intact.
        """
        await self.db.refresh(survey, attribute_names=["updated_at"])

    async def list(
        self,
        limit: int,
        offset: int,
        params: SurveyListingParams,
    ) -> tuple[list[tuple[Survey, int]], int]:
        """Return a paginated list of ``(survey, question_count)`` rows and the
        total matching count.

        The summary view needs only a question count, so ``questions`` is
        suppressed with ``noload`` and the count comes from a correlated
        subquery — avoiding hydrating every question/option just to call
        ``len()``.
        """
        count_query = select(func.count()).select_from(Survey)
        rows, total = await execute_paginated_rows(
            self.db,
            self._listing_base_query(),
            count_query,
            SURVEY_SORT_CLAUSES[params.sort_order],
            limit,
            offset,
            conditions=self._listing_conditions(params),
        )
        return list(rows), total

    async def list_all_for_export(
        self, params: SurveyListingParams
    ) -> list[tuple[Survey, int]]:
        """Return every ``(survey, question_count)`` row matching the filters.

        Shares the base query, ``_listing_conditions`` and ``SURVEY_SORT_CLAUSES``
        with ``list``, so an export always carries the same rows in the same
        order as the listing it was launched from.
        """
        rows = await execute_all_rows(
            self.db,
            self._listing_base_query(),
            SURVEY_SORT_CLAUSES[params.sort_order],
            conditions=self._listing_conditions(params),
        )
        return list(rows)

    async def create(
        self,
        *,
        name: str,
        description: str | None,
        response_target: SurveyResponseTarget,
        instrument_type,
        created_by_id: UUID,
        questions: list[QuestionInputData],
    ) -> Survey:
        """Persist a new survey aggregate.

        Raises:
            UniqueConstraintError: If the (case-insensitive) name is already taken.
                The caller pre-checks with ``name_exists``; this guards against races.
        """
        survey = Survey(
            name=name.strip(),
            description=description,
            response_target=response_target,
            instrument_type=instrument_type,
            created_by_id=created_by_id,
            questions=[
                self._build_question(q, position)
                for position, q in enumerate(questions)
            ],
        )
        await self._flush_aggregate(survey, name)
        return survey

    async def reconcile(
        self,
        survey: Survey,
        *,
        name: str,
        description: str | None,
        response_target: SurveyResponseTarget,
        instrument_type,
        questions: list[QuestionInputData],
    ) -> Survey:
        """Declaratively reconcile a survey to match the supplied configuration.

        Questions and options are diffed by id: known ids are updated in place, ids
        absent from the payload are deleted (ORM cascade), and entries without an id
        are inserted. Array position becomes the persisted ``position``.

        Raises:
            InvalidSurveyPayloadError: A supplied question/option id does not belong
                to this survey.
            UniqueConstraintError: The new name collides with another survey.
        """
        survey.name = name.strip()
        survey.description = description
        survey.response_target = response_target
        survey.instrument_type = instrument_type
        self._reconcile_questions(survey, questions)
        await self._flush_aggregate(survey, name)
        return survey

    async def duplicate(
        self,
        source: Survey,
        *,
        new_name: str,
        created_by_id: UUID,
    ) -> Survey:
        """Deep-copy ``source`` into a fresh survey with new ids and no responses.

        The copy inherits the source's ``is_active`` state, so duplicating a paused
        survey yields a paused copy rather than silently publishing it.

        Raises:
            UniqueConstraintError: If ``new_name`` is already taken. The caller
                pre-generates a free name; this guards against a race.
        """
        survey = Survey(
            name=new_name.strip(),
            description=source.description,
            response_target=source.response_target,
            instrument_type=source.instrument_type,
            is_active=source.is_active,
            created_by_id=created_by_id,
            questions=[
                self._build_question(q, position)
                for position, q in enumerate(source.questions)
            ],
        )
        await self._flush_aggregate(survey, new_name)
        return survey

    async def delete(self, survey: Survey) -> None:
        """Delete a survey. ORM cascade removes questions, options and audience rows."""
        await self.db.delete(survey)
        await self.db.flush()

    async def update_active(self, survey: Survey, is_active: bool) -> Survey:
        """Toggle a survey's active flag."""
        survey.is_active = is_active
        await self.db.flush()
        await self._refresh_updated_at(survey)
        return survey

    async def increment_response_count(self, survey_id: UUID) -> None:
        """Atomically increment a survey's response_count by 1.

        A single ``UPDATE ... SET x = x + 1``, not a read-modify-write, so it
        stays correct under concurrent submissions.
        """
        await self.db.execute(
            update(Survey)
            .where(Survey.id == survey_id)
            .values(response_count=Survey.response_count + 1)
        )

    async def list_available(
        self,
        *,
        limit: int,
        offset: int,
    ) -> tuple[list[tuple[Survey, int]], int]:
        """Return ``(survey, question_count)`` rows for every active survey, and
        the total matching count."""
        question_count = self._question_count_subquery()
        base_query = (
            select(Survey, question_count.label("question_count"))
            .options(noload(Survey.questions))
            .where(Survey.is_active.is_(True))
        )
        count_query = (
            select(func.count()).select_from(Survey).where(Survey.is_active.is_(True))
        )
        rows, total = await execute_paginated_rows(
            self.db, base_query, count_query, desc(Survey.created_at), limit, offset
        )
        return list(rows), total
