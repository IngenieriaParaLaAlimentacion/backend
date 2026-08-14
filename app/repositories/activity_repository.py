from uuid import UUID

from sqlalchemy import Select, Subquery, func, literal, select, union_all
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain.activity import ActivityItemDomain, ActivityType
from app.domain.measurement import MeasurementListItemDomain
from app.domain.subject import SubjectBase
from app.domain.subject_event import SubjectEventType
from app.domain.survey_response import SurveyResponseListItemDomain
from app.models.measurement import Measurement
from app.models.subject import Subject
from app.models.subject_event import SubjectEvent
from app.models.survey_response import SurveyResponse


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

    async def _hydrate_page_rows(
        self, page_rows: list[Row]
    ) -> tuple[
        dict[UUID, Subject], dict[UUID, Measurement], dict[UUID, SurveyResponse]
    ]:
        """Fetch the full row for every id in the current page, grouped by type."""
        subject_ids = [row.id for row in page_rows if row.type == ActivityType.SUBJECT]
        measurement_ids = [
            row.id for row in page_rows if row.type == ActivityType.MEASUREMENT
        ]
        survey_response_ids = [
            row.id for row in page_rows if row.type == ActivityType.SURVEY_RESPONSE
        ]
        subjects_by_id = await self._get_subjects_by_id(subject_ids)
        measurements_by_id = await self._get_measurements_by_id(measurement_ids)
        survey_responses_by_id = await self._get_survey_responses_by_id(
            survey_response_ids
        )
        return subjects_by_id, measurements_by_id, survey_responses_by_id

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

    def _assemble_items(
        self,
        page_rows: list[Row],
        subjects_by_id: dict[UUID, Subject],
        measurements_by_id: dict[UUID, Measurement],
        survey_responses_by_id: dict[UUID, SurveyResponse],
    ) -> list[ActivityItemDomain]:
        """Rebuild domain items in the page's original (already sorted) order."""
        items = []
        for row in page_rows:
            if row.type == ActivityType.SUBJECT:
                items.append(
                    ActivityItemDomain(
                        type=ActivityType.SUBJECT,
                        occurred_at=row.occurred_at,
                        subject=SubjectBase.from_db(subjects_by_id[row.id]),
                    )
                )
            elif row.type == ActivityType.MEASUREMENT:
                items.append(
                    ActivityItemDomain(
                        type=ActivityType.MEASUREMENT,
                        occurred_at=row.occurred_at,
                        measurement=MeasurementListItemDomain.from_db(
                            measurements_by_id[row.id]
                        ),
                    )
                )
            else:
                items.append(
                    ActivityItemDomain(
                        type=ActivityType.SURVEY_RESPONSE,
                        occurred_at=row.occurred_at,
                        survey_response=SurveyResponseListItemDomain.from_db(
                            survey_responses_by_id[row.id]
                        ),
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
        registrations, measurement uploads, and survey responses, and the total
        matching count.
        """
        feed_query = self._build_feed_subquery(actor_id, activity_type)

        total = await self.db.scalar(select(func.count()).select_from(feed_query))
        page_rows = await self._fetch_page_rows(feed_query, limit, offset)

        (
            subjects_by_id,
            measurements_by_id,
            survey_responses_by_id,
        ) = await self._hydrate_page_rows(page_rows)
        items = self._assemble_items(
            page_rows, subjects_by_id, measurements_by_id, survey_responses_by_id
        )
        return items, total
