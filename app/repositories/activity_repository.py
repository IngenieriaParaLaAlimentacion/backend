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
from app.utils.db import execute_paginated_rows


def _feed_branch(
    activity_type: ActivityType,
    id_col,
    ts_col,
    actor_col,
    *extra_conditions,
) -> Callable[[UUID], Select]:
    """Build the branch builder for one activity type.

    Every branch of the feed union has the same shape -- id, a literal type
    tag, and the event timestamp labelled ``occurred_at`` so the columns line up
    -- filtered to the rows a given actor is responsible for. This closes over
    the per-type columns and returns the builder that still needs the actor.

    ``extra_conditions`` is for the branches whose "authored by" is narrower
    than one column, e.g. subjects, which also have to pin the event type.
    """

    def build(actor_id: UUID) -> Select:
        return select(
            id_col.label("id"),
            literal(activity_type.value).label("type"),
            ts_col.label("occurred_at"),
        ).where(actor_col == actor_id, *extra_conditions)

    return build


class ActivityRepository:
    """Persistence operations for a user's recent-activity feed."""

    def __init__(self, db: AsyncSession):
        self.db = db

    def _build_feed_subquery(
        self, actor_id: UUID, activity_types: list[ActivityType] | None
    ) -> Subquery:
        """Build the id/type/occurred_at UNION ALL of the requested branches.

        `activity_types` is the raw request filter: None/empty means every
        type, and it may contain duplicates because FastAPI does not collapse
        repeated query values. Collecting it into a set is what makes a
        repeated `?type=x&type=x` idempotent -- appending the same branch
        twice would silently double both the rows and the total.

        Iteration is over `ActivityType` (declaration order), filtered by
        membership, so branch order is deterministic and independent of both
        the set's iteration order and the request order.
        """
        requested = set(activity_types) if activity_types else set(ActivityType)
        branches = [
            self._FEED_BRANCH_BUILDERS[activity_type](actor_id)
            for activity_type in ActivityType
            if activity_type in requested
        ]
        return union_all(*branches).subquery()

    # Per activity type: the builder for its id/type/occurred_at branch of the
    # feed union, each one an application of `_feed_branch`.
    # No fallback entry on purpose: `_build_feed_subquery` iterates the enum and
    # looks each member up here, so a type added to the enum but forgotten here
    # raises a KeyError instead of silently vanishing from the unfiltered feed.
    _FEED_BRANCH_BUILDERS: ClassVar[dict[ActivityType, Callable[[UUID], Select]]] = {
        # Subjects read from `subject_events`: that is where authorship and
        # timing are recorded, not on the subject row itself.
        ActivityType.SUBJECT: _feed_branch(
            ActivityType.SUBJECT,
            SubjectEvent.subject_id,
            SubjectEvent.occurred_at,
            SubjectEvent.actor_id,
            SubjectEvent.event_type == SubjectEventType.SUBJECT_CREATED,
        ),
        ActivityType.MEASUREMENT: _feed_branch(
            ActivityType.MEASUREMENT,
            Measurement.id,
            Measurement.measured_at,
            Measurement.responsible_id,
        ),
        ActivityType.SURVEY_RESPONSE: _feed_branch(
            ActivityType.SURVEY_RESPONSE,
            SurveyResponse.id,
            SurveyResponse.event_at,
            SurveyResponse.submitted_by_id,
        ),
        ActivityType.FOOD_INTAKE: _feed_branch(
            ActivityType.FOOD_INTAKE,
            FoodIntake.id,
            FoodIntake.occurred_at,
            FoodIntake.responsible_id,
        ),
        ActivityType.FOOD_OUTFLOW: _feed_branch(
            ActivityType.FOOD_OUTFLOW,
            FoodOutflow.id,
            FoodOutflow.occurred_at,
            FoodOutflow.responsible_id,
        ),
    }

    @staticmethod
    def _ids_of(page_rows: list[Row], activity_type: ActivityType) -> list[UUID]:
        """Return the ids in the page that belong to one activity type."""
        return [row.id for row in page_rows if row.type == activity_type]

    async def _hydrate_page_rows(
        self, page_rows: list[Row]
    ) -> dict[ActivityType, dict[UUID, object]]:
        """Fetch the full row for every id in the current page, keyed by type.

        Each per-type fetch short-circuits to `{}` when the page carries no row
        of that type, so a page costs at most one query per type present.
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
    # No fallback entry on purpose: a type added to the enum but forgotten here
    # raises instead of being silently mislabelled as another type.
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
        activity_types: list[ActivityType] | None,
    ) -> tuple[list[ActivityItemDomain], int]:
        """Return a paginated, date-descending merge of the actor's own subject
        registrations, measurement uploads, survey responses and food movements
        (intakes and outflows), and the total matching count.

        `activity_types` selects which branches enter the union; None or empty
        means every type. `total` and the page slice read the same subquery
        object, so they cannot disagree about the filter.

        `id DESC` breaks ties on `occurred_at` deterministically so pagination
        never skips or repeats a row across pages.
        """
        feed_query = self._build_feed_subquery(actor_id, activity_types)

        page_rows, total = await execute_paginated_rows(
            self.db,
            select(feed_query.c.id, feed_query.c.type, feed_query.c.occurred_at),
            select(func.count()).select_from(feed_query),
            (feed_query.c.occurred_at.desc(), feed_query.c.id.desc()),
            limit,
            offset,
        )

        hydrated = await self._hydrate_page_rows(page_rows)
        items = self._assemble_items(page_rows, hydrated)
        return items, total
