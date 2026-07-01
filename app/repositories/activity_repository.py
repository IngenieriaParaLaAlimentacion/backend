from uuid import UUID

from sqlalchemy import func, literal, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain.activity import ActivityItemDomain, ActivityType
from app.domain.measurement import MeasurementListItemDomain
from app.domain.subject import SubjectBase
from app.domain.subject_event import SubjectEventType
from app.models.establishment import Establishment
from app.models.measurement import Measurement
from app.models.subject import Subject
from app.models.subject_event import SubjectEvent


class ActivityRepository:
    """Persistence operations for a user's recent-activity feed."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_activity_feed(
        self,
        actor_id: UUID,
        limit: int,
        offset: int,
        activity_type: ActivityType | None,
    ) -> tuple[list[ActivityItemDomain], int]:
        """Return a paginated, date-descending merge of the actor's own subject
        registrations and measurement uploads, and the total matching count.
        """
        branches = []
        if activity_type is None or activity_type == ActivityType.SUBJECT:
            branches.append(
                select(
                    Subject.id.label("id"),
                    literal(ActivityType.SUBJECT.value).label("type"),
                    SubjectEvent.occurred_at.label("occurred_at"),
                )
                .select_from(SubjectEvent)
                .join(Subject, Subject.id == SubjectEvent.subject_id)
                .where(
                    SubjectEvent.actor_id == actor_id,
                    SubjectEvent.event_type == SubjectEventType.SUBJECT_CREATED,
                )
            )
        if activity_type is None or activity_type == ActivityType.MEASUREMENT:
            branches.append(
                select(
                    Measurement.id.label("id"),
                    literal(ActivityType.MEASUREMENT.value).label("type"),
                    Measurement.measured_at.label("occurred_at"),
                ).where(Measurement.responsible_id == actor_id)
            )

        feed = union_all(*branches).subquery()

        total = await self.db.scalar(select(func.count()).select_from(feed))
        page_rows = (
            await self.db.execute(
                select(feed.c.id, feed.c.type, feed.c.occurred_at)
                .order_by(feed.c.occurred_at.desc(), feed.c.id.desc())
                .limit(limit)
                .offset(offset)
            )
        ).all()

        subject_ids = [row.id for row in page_rows if row.type == ActivityType.SUBJECT]
        measurement_ids = [
            row.id for row in page_rows if row.type == ActivityType.MEASUREMENT
        ]

        subjects_by_id = {}
        if subject_ids:
            result = await self.db.execute(
                select(Subject).where(Subject.id.in_(subject_ids))
            )
            subjects_by_id = {s.id: s for s in result.scalars().all()}

        measurements_by_id = {}
        if measurement_ids:
            result = await self.db.execute(
                select(Measurement)
                .join(Subject, Measurement.subject_id == Subject.id)
                .join(Establishment, Measurement.establishment_id == Establishment.id)
                .options(
                    selectinload(Measurement.subject),
                    selectinload(Measurement.establishment),
                    selectinload(Measurement.responsible),
                )
                .where(Measurement.id.in_(measurement_ids))
            )
            measurements_by_id = {m.id: m for m in result.scalars().all()}

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
            else:
                items.append(
                    ActivityItemDomain(
                        type=ActivityType.MEASUREMENT,
                        occurred_at=row.occurred_at,
                        measurement=MeasurementListItemDomain.from_db(
                            measurements_by_id[row.id]
                        ),
                    )
                )

        return items, total
