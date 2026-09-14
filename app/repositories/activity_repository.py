from collections.abc import Callable
from typing import ClassVar
from uuid import UUID

from sqlalchemy import Select, Subquery, func, literal, select, union_all
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain.activity import ActivityItemDomain, ActivityType
from app.domain.food_intake import FoodMovementListItemDomain
from app.domain.measurement import MeasurementListItemDomain
from app.domain.subject import SubjectBase
from app.domain.subject_event import SubjectEventType
from app.domain.survey_response import SurveyResponseListItemDomain
from app.models.food_intakes.food_intake import FoodIntake
from app.models.food_intakes.food_intake_item import FoodIntakeItem
from app.models.food_outflows.food_outflow import FoodOutflow
from app.models.food_outflows.food_outflow_item import FoodOutflowItem
from app.models.measurements.measurement import Measurement
from app.models.subjects.subject import Subject
from app.models.subjects.subject_event import SubjectEvent
from app.models.surveys.survey_response import SurveyResponse


class ActivityRepository:
    """Persistence operations for a user's recent-activity feed."""

    def __init__(self, db: AsyncSession):
        self.db = db

    def _build_feed_subquery(
        self, actor_id: UUID, activity_type: ActivityType | None
    ) -> Subquery:
        """Build the id/type/occurred_at UNION ALL of the requested branches."""
        branches = []
        if activity_type is None or activity_type == ActivityType.SUBJECT:
            branches.append(self._build_subjects_created_query(actor_id))
        if activity_type is None or activity_type == ActivityType.MEASUREMENT:
            branches.append(self._build_measurements_taken_query(actor_id))
        if activity_type is None or activity_type == ActivityType.SURVEY_RESPONSE:
            branches.append(self._build_survey_responses_query(actor_id))
        if activity_type is None or activity_type == ActivityType.FOOD_INTAKE:
            branches.append(self._build_food_intakes_query(actor_id))
        if activity_type is None or activity_type == ActivityType.FOOD_OUTFLOW:
            branches.append(self._build_food_outflows_query(actor_id))
        return union_all(*branches).subquery()

    def _build_subjects_created_query(self, actor_id: UUID) -> Select:
        """Return the query for the subjects that the `actor_id` registered.

        One row per subject, paired with its creation timestamp. Reads from
        `subject_events` because that's where authorship and timing are
        recorded, not on the subject row itself.
        """
        return select(
            SubjectEvent.subject_id.label("id"),
            literal(ActivityType.SUBJECT.value).label("type"),
            SubjectEvent.occurred_at.label("occurred_at"),
        ).where(
            SubjectEvent.actor_id == actor_id,
            SubjectEvent.event_type == SubjectEventType.SUBJECT_CREATED,
        )

    def _build_measurements_taken_query(self, actor_id: UUID) -> Select:
        """Return the query for the measurements ``actor_id`` is responsible for.

        One row per measurement, paired with the timestamp it was measured at.
        """
        return select(
            Measurement.id.label("id"),
            literal(ActivityType.MEASUREMENT.value).label("type"),
            Measurement.measured_at.label("occurred_at"),
        ).where(Measurement.responsible_id == actor_id)

    def _build_survey_responses_query(self, actor_id: UUID) -> Select:
        """Return the query for the survey responses ``actor_id`` submitted.

        One row per response, paired with the timestamp it was completed at.
        """
        return select(
            SurveyResponse.id.label("id"),
            literal(ActivityType.SURVEY_RESPONSE.value).label("type"),
            SurveyResponse.event_at.label("occurred_at"),
        ).where(SurveyResponse.submitted_by_id == actor_id)

    def _build_food_intakes_query(self, actor_id: UUID) -> Select:
        """Return the query for the food intakes ``actor_id`` registered.

        One row per intake, paired with the timestamp the food arrived.
        ``received_at`` is labelled ``occurred_at`` so every branch of the
        union exposes the same three columns; the intake payload keeps the
        table's own column name.
        """
        return select(
            FoodIntake.id.label("id"),
            literal(ActivityType.FOOD_INTAKE.value).label("type"),
            FoodIntake.received_at.label("occurred_at"),
        ).where(FoodIntake.responsible_id == actor_id)

    def _build_food_outflows_query(self, actor_id: UUID) -> Select:
        """Return the query for the food outflows ``actor_id`` registered.

        One row per outflow, paired with the timestamp the food left.
        """
        return select(
            FoodOutflow.id.label("id"),
            literal(ActivityType.FOOD_OUTFLOW.value).label("type"),
            FoodOutflow.occurred_at.label("occurred_at"),
        ).where(FoodOutflow.responsible_id == actor_id)

    async def _fetch_page_rows(
        self, feed_query: Subquery, limit: int, offset: int
    ) -> list[Row]:
        """Slice the merged feed: id + type + timestamp only, no hydration yet.

        `id DESC` breaks ties on `occurred_at` deterministically so
        pagination never skips or repeats a row across pages.
        """
        result = await self.db.execute(
            select(feed_query.c.id, feed_query.c.type, feed_query.c.occurred_at)
            .order_by(feed_query.c.occurred_at.desc(), feed_query.c.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return result.all()

    @staticmethod
    def _ids_of(page_rows: list[Row], activity_type: ActivityType) -> list[UUID]:
        """Return the ids in the page that belong to one activity type."""
        return [row.id for row in page_rows if row.type == activity_type]

    async def _hydrate_page_rows(
        self, page_rows: list[Row]
    ) -> dict[ActivityType, dict[UUID, object]]:
        """Fetch the full row for every id in the current page, keyed by type.

        Returns a mapping per activity type so a new type is one entry here and
        one entry in `_ITEM_BUILDERS`, with no positional argument to keep in
        sync. Each per-type fetch short-circuits to `{}` when the page carries
        no row of that type, so an unfiltered page costs at most one query per
        type present.
        """
        return {
            ActivityType.SUBJECT: await self._get_subjects_by_id(
                self._ids_of(page_rows, ActivityType.SUBJECT)
            ),
            ActivityType.MEASUREMENT: await self._get_measurements_by_id(
                self._ids_of(page_rows, ActivityType.MEASUREMENT)
            ),
            ActivityType.SURVEY_RESPONSE: await self._get_survey_responses_by_id(
                self._ids_of(page_rows, ActivityType.SURVEY_RESPONSE)
            ),
            ActivityType.FOOD_INTAKE: await self._get_food_intakes_by_id(
                self._ids_of(page_rows, ActivityType.FOOD_INTAKE)
            ),
            ActivityType.FOOD_OUTFLOW: await self._get_food_outflows_by_id(
                self._ids_of(page_rows, ActivityType.FOOD_OUTFLOW)
            ),
        }

    async def _get_subjects_by_id(self, subject_ids: list[UUID]) -> dict[UUID, Subject]:
        if not subject_ids:
            return {}
        result = await self.db.execute(
            select(Subject).where(Subject.id.in_(subject_ids))
        )
        return {subject.id: subject for subject in result.scalars().all()}

    async def _get_measurements_by_id(
        self, measurement_ids: list[UUID]
    ) -> dict[UUID, Measurement]:
        if not measurement_ids:
            return {}
        result = await self.db.execute(
            select(Measurement)
            .options(
                selectinload(Measurement.subject),
                selectinload(Measurement.establishment),
                selectinload(Measurement.responsible),
            )
            .where(Measurement.id.in_(measurement_ids))
        )
        return {measurement.id: measurement for measurement in result.scalars().all()}

    async def _get_survey_responses_by_id(
        self, response_ids: list[UUID]
    ) -> dict[UUID, SurveyResponse]:
        if not response_ids:
            return {}
        result = await self.db.execute(
            select(SurveyResponse)
            .options(
                selectinload(SurveyResponse.survey),
                selectinload(SurveyResponse.establishment),
                selectinload(SurveyResponse.subject),
            )
            .where(SurveyResponse.id.in_(response_ids))
        )
        return {response.id: response for response in result.scalars().all()}

    async def _get_food_intakes_by_id(
        self, intake_ids: list[UUID]
    ) -> dict[UUID, FoodIntake]:
        if not intake_ids:
            return {}
        result = await self.db.execute(
            select(FoodIntake)
            .options(
                selectinload(FoodIntake.establishment),
                selectinload(FoodIntake.items).selectinload(FoodIntakeItem.food),
            )
            .where(FoodIntake.id.in_(intake_ids))
        )
        return {intake.id: intake for intake in result.scalars().all()}

    async def _get_food_outflows_by_id(
        self, outflow_ids: list[UUID]
    ) -> dict[UUID, FoodOutflow]:
        if not outflow_ids:
            return {}
        result = await self.db.execute(
            select(FoodOutflow)
            .options(
                selectinload(FoodOutflow.establishment),
                selectinload(FoodOutflow.items).selectinload(FoodOutflowItem.food),
            )
            .where(FoodOutflow.id.in_(outflow_ids))
        )
        return {outflow.id: outflow for outflow in result.scalars().all()}

    # Per activity type: the `ActivityItemDomain` field to populate, and the
    # domain builder that turns the hydrated ORM row into that field's value.
    # A new activity type is one entry here plus one in `_hydrate_page_rows`;
    # there is deliberately no fallback branch, so a type added to the enum and
    # forgotten here fails loudly instead of being mislabelled as another type.
    _ITEM_BUILDERS: ClassVar[
        dict[ActivityType, tuple[str, Callable[[object], object]]]
    ] = {
        ActivityType.SUBJECT: ("subject", SubjectBase.from_db),
        ActivityType.MEASUREMENT: ("measurement", MeasurementListItemDomain.from_db),
        ActivityType.SURVEY_RESPONSE: (
            "survey_response",
            SurveyResponseListItemDomain.from_db,
        ),
        ActivityType.FOOD_INTAKE: (
            "food_intake",
            FoodMovementListItemDomain.from_intake,
        ),
        ActivityType.FOOD_OUTFLOW: (
            "food_outflow",
            FoodMovementListItemDomain.from_outflow,
        ),
    }

    def _assemble_items(
        self,
        page_rows: list[Row],
        hydrated: dict[ActivityType, dict[UUID, object]],
    ) -> list[ActivityItemDomain]:
        """Rebuild domain items in the page's original (already sorted) order."""
        items = []
        for row in page_rows:
            activity_type = ActivityType(row.type)
            field, build = self._ITEM_BUILDERS[activity_type]
            items.append(
                ActivityItemDomain(
                    type=activity_type,
                    occurred_at=row.occurred_at,
                    **{field: build(hydrated[activity_type][row.id])},
                )
            )
        return items

    async def get_activity_feed(
        self,
        actor_id: UUID,
        limit: int,
        offset: int,
        activity_type: ActivityType | None,
    ) -> tuple[list[ActivityItemDomain], int]:
        """Return a paginated, date-descending merge of the actor's own subject
        registrations, measurement uploads, survey responses and food movements
        (intakes and outflows), and the total matching count.
        """
        feed_query = self._build_feed_subquery(actor_id, activity_type)

        total = await self.db.scalar(select(func.count()).select_from(feed_query))
        page_rows = await self._fetch_page_rows(feed_query, limit, offset)

        hydrated = await self._hydrate_page_rows(page_rows)
        items = self._assemble_items(page_rows, hydrated)
        return items, total
