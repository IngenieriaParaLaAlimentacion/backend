from __future__ import annotations

from uuid import UUID

from sqlalchemy import and_, asc, desc, exists, func, or_, select, true, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import noload

from app.domain.survey import (
    QuestionInputData,
    SurveyListingParams,
    SurveyScope,
    SurveySortOrder,
)
from app.exceptions.domain_exceptions import (
    InvalidSurveyPayloadError,
    UniqueConstraintError,
)
from app.models.establishment import Establishment
from app.models.survey import Survey
from app.models.survey_establishment import SurveyEstablishment
from app.models.survey_question import SurveyQuestion
from app.models.survey_question_option import SurveyQuestionOption
from app.utils.db import escape_like

# Maps each SurveySortOrder value to its SQLAlchemy order clause.
# KeyError on an unmapped value is intentional: it surfaces missing cases immediately.
_SORT_CLAUSES = {
    SurveySortOrder.NAME_ASC: asc(func.lower(Survey.name)),
    SurveySortOrder.NAME_DESC: desc(func.lower(Survey.name)),
    SurveySortOrder.NEWEST: desc(Survey.created_at),
    SurveySortOrder.OLDEST: asc(Survey.created_at),
}


class SurveyRepository:
    """Persistence for the survey aggregate (survey + questions + options + audience).

    The ``questions``/``options``/``establishments`` relationships are eager-loaded via
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

    @staticmethod
    def _listing_conditions(params: SurveyListingParams) -> list:
        """Build the filter conditions for a survey listing."""
        conditions = []
        if params.search:
            pattern = f"%{escape_like(params.search)}%"
            conditions.append(Survey.name.ilike(pattern, escape="\\"))
        if params.created_by is not None:
            conditions.append(Survey.created_by_id == params.created_by)
        if params.scope is not None:
            conditions.append(Survey.scope == params.scope)
        if params.is_active is not None:
            conditions.append(Survey.is_active == params.is_active)
        return conditions

    @staticmethod
    def _available_scope_condition(actor_establishment_ids: list[UUID] | None):
        if actor_establishment_ids is None:
            return true()
        targeted_match = and_(
            Survey.scope == SurveyScope.TARGETED,
            exists().where(
                SurveyEstablishment.survey_id == Survey.id,
                SurveyEstablishment.establishment_id.in_(actor_establishment_ids),
            ),
        )
        return or_(Survey.scope == SurveyScope.GENERIC, targeted_match)

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

    async def _assign_establishments(
        self, survey: Survey, establishment_ids: list[UUID]
    ) -> None:
        if establishment_ids:
            result = await self.db.execute(
                select(Establishment).where(Establishment.id.in_(establishment_ids))
            )
            survey.establishments = list(result.scalars().all())
        else:
            survey.establishments = []

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
        one column so the eager-loaded questions/establishments stay intact.
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

        The summary view needs only a question count, so ``questions`` and
        ``establishments`` are suppressed with ``noload`` and the count comes from a
        correlated subquery — avoiding hydrating every question/option/establishment
        just to call ``len()``.
        """
        question_count = self._question_count_subquery()
        base_query = select(Survey, question_count.label("question_count")).options(
            noload(Survey.questions), noload(Survey.establishments)
        )
        count_query = select(func.count()).select_from(Survey)
        for condition in self._listing_conditions(params):
            base_query = base_query.where(condition)
            count_query = count_query.where(condition)
        order_by = _SORT_CLAUSES[params.sort_order]
        paginated = base_query.order_by(order_by).limit(limit).offset(offset)
        total = (await self.db.execute(count_query)).scalar_one()
        rows = (await self.db.execute(paginated)).all()
        return [(row[0], row[1]) for row in rows], total

    async def create(
        self,
        *,
        name: str,
        description: str | None,
        scope,
        instrument_type,
        created_by_id: UUID,
        questions: list[QuestionInputData],
        establishment_ids: list[UUID],
    ) -> Survey:
        """Persist a new survey aggregate.

        Raises:
            UniqueConstraintError: If the (case-insensitive) name is already taken.
                The caller pre-checks with ``name_exists``; this guards against races.
        """
        survey = Survey(
            name=name.strip(),
            description=description,
            scope=scope,
            instrument_type=instrument_type,
            created_by_id=created_by_id,
            questions=[
                self._build_question(q, position)
                for position, q in enumerate(questions)
            ],
        )
        await self._assign_establishments(survey, establishment_ids)
        await self._flush_aggregate(survey, name)
        return survey

    async def reconcile(
        self,
        survey: Survey,
        *,
        name: str,
        description: str | None,
        scope,
        instrument_type,
        questions: list[QuestionInputData],
        establishment_ids: list[UUID],
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
        survey.scope = scope
        survey.instrument_type = instrument_type
        self._reconcile_questions(survey, questions)
        await self._assign_establishments(survey, establishment_ids)
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
            scope=source.scope,
            instrument_type=source.instrument_type,
            is_active=source.is_active,
            created_by_id=created_by_id,
            questions=[
                self._build_question(q, position)
                for position, q in enumerate(source.questions)
            ],
        )
        await self._assign_establishments(survey, [e.id for e in source.establishments])
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
        actor_establishment_ids: list[UUID] | None,
        limit: int,
        offset: int,
    ) -> tuple[list[tuple[Survey, int]], int]:
        """Return ``(survey, question_count)`` rows for active surveys the caller
        may respond to, and the total matching count.

        Matches generic surveys plus targeted surveys aimed at one of
        ``actor_establishment_ids``. ``actor_establishment_ids=None`` (an
        admin/superadmin caller) matches every targeted survey unconditionally,
        mirroring the establishment-access bypass used for submission.
        """
        question_count = self._question_count_subquery()
        scope_condition = self._available_scope_condition(actor_establishment_ids)
        base_query = (
            select(Survey, question_count.label("question_count"))
            .options(noload(Survey.questions), noload(Survey.establishments))
            .where(Survey.is_active.is_(True), scope_condition)
        )
        count_query = (
            select(func.count())
            .select_from(Survey)
            .where(Survey.is_active.is_(True), scope_condition)
        )
        paginated = (
            base_query.order_by(desc(Survey.created_at)).limit(limit).offset(offset)
        )
        total = (await self.db.execute(count_query)).scalar_one()
        rows = (await self.db.execute(paginated)).all()
        return [(row[0], row[1]) for row in rows], total
