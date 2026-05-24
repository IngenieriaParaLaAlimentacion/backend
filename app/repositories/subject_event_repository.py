from dataclasses import asdict
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.subject_event import (
    EventPayload,
    SubjectEventHistory,
    SubjectEventRecord,
    SubjectEventType,
)
from app.models.subject_event import SubjectEvent
from app.utils.db import execute_paginated


class SubjectEventRepository:
    """Repository for subject event persistence and history queries."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def append(
        self,
        *,
        subject_id: UUID,
        actor_id: UUID,
        event_type: SubjectEventType,
        payload: EventPayload | None = None,
    ) -> None:
        """Persist a new subject event to the audit log."""
        event = SubjectEvent(
            subject_id=subject_id,
            actor_id=actor_id,
            event_type=event_type,
            payload=asdict(payload) if payload is not None else None,
        )
        self.db.add(event)
        await self.db.flush()

    async def get_history(
        self,
        subject_id: UUID,
        *,
        page: int = 1,
        page_size: int = 20,
    ) -> SubjectEventHistory:
        """Return a page of events for a subject, ordered by most recent."""
        condition = SubjectEvent.subject_id == subject_id
        base_query = select(SubjectEvent).where(condition)
        count_query = select(func.count()).select_from(SubjectEvent).where(condition)

        raw_events, total = await execute_paginated(
            self.db,
            base_query,
            count_query,
            SubjectEvent.occurred_at.desc(),
            limit=page_size,
            offset=(page - 1) * page_size,
        )

        records = [
            SubjectEventRecord(
                event_type=event.event_type,
                occurred_at=event.occurred_at,
                actor_id=event.actor_id,
                payload=EventPayload(**event.payload)
                if event.payload
                else EventPayload(),
            )
            for event in raw_events
        ]

        return SubjectEventHistory(
            events=records,
            total_events=total,
            page=page,
            page_size=page_size,
        )
