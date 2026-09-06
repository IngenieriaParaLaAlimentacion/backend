from dataclasses import asdict
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.subject_event import EventPayload, SubjectEventType
from app.models.subjects.subject_event import SubjectEvent
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
    ) -> tuple[list[SubjectEvent], int]:
        """Return a page of events for a subject (most recent first) and
        the total count."""
        condition = SubjectEvent.subject_id == subject_id
        base_query = select(SubjectEvent).where(condition)
        count_query = select(func.count()).select_from(SubjectEvent).where(condition)

        return await execute_paginated(
            self.db,
            base_query,
            count_query,
            SubjectEvent.occurred_at.desc(),
            limit=page_size,
            offset=(page - 1) * page_size,
        )
