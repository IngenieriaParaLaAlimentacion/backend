import uuid

import pytest
from fastapi import status

from tests.integration.subjects.conftest import _upload, _upload_with_id

pytestmark = pytest.mark.asyncio


class TestSubjectEventLog:
    async def test_registration_creates_event(
        self, client, field_worker_headers, field_worker_user_id
    ):
        """Creating a subject persists a SUBJECT_CREATED event linked to the actor."""
        from sqlalchemy import select

        from app.db.database import AsyncSessionLocal
        from app.domain.subject_event import SubjectEventType
        from app.models.subjects.subject_event import SubjectEvent

        response = await _upload(client, field_worker_headers)
        assert response.status_code == status.HTTP_201_CREATED
        subject_id = uuid.UUID(response.json()["id"])

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(SubjectEvent).where(SubjectEvent.subject_id == subject_id)
            )
            events = result.scalars().all()

        assert len(events) == 1
        assert events[0].event_type == SubjectEventType.SUBJECT_CREATED
        assert events[0].actor_id == field_worker_user_id
        assert events[0].payload is None

    async def test_failed_registration_creates_no_event(
        self, client, field_worker_headers
    ):
        """A rejected registration (duplicate DNI) does not persist any event."""
        from sqlalchemy import select

        from app.db.database import AsyncSessionLocal
        from app.models.subjects.subject_event import SubjectEvent

        await _upload(client, field_worker_headers)
        response = await _upload(client, field_worker_headers)
        assert response.status_code == status.HTTP_409_CONFLICT

        async with AsyncSessionLocal() as session:
            result = await session.execute(select(SubjectEvent))
            events = result.scalars().all()

        assert len(events) == 1

    async def test_replay_creates_no_second_event(self, client, field_worker_headers):
        """Replaying the same id does not append a second SUBJECT_CREATED event."""
        from sqlalchemy import select

        from app.db.database import AsyncSessionLocal
        from app.models.subjects.subject_event import SubjectEvent

        subject_id = uuid.uuid4()
        await _upload_with_id(client, field_worker_headers, subject_id)
        replay = await _upload_with_id(client, field_worker_headers, subject_id)
        assert replay.status_code == status.HTTP_200_OK

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(SubjectEvent).where(SubjectEvent.subject_id == subject_id)
            )
            events = result.scalars().all()

        assert len(events) == 1
