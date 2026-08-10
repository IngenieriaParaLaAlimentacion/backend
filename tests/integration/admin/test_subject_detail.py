import uuid

import pytest
from fastapi import status

from tests.integration.admin.conftest import (
    ADMIN_SUBJECTS_URL,
    SUBJECTS_URL,
    _subject_body,
)

pytestmark = pytest.mark.asyncio


class TestAdminSubjectDetail:
    async def test_returns_200_with_subject_and_events(
        self, client, field_worker_headers, admin_headers
    ):
        """Admin retrieves a subject with its full event history."""
        created = (
            await client.post(
                SUBJECTS_URL, json=_subject_body(), headers=field_worker_headers
            )
        ).json()
        response = await client.get(
            f"{ADMIN_SUBJECTS_URL}/{created['id']}", headers=admin_headers
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["id"] == created["id"]
        assert data["dni"] == created["dni"]
        assert data["events"]["total"] == 1
        assert data["events"]["items"][0]["event_type"] == "SUBJECT_CREATED"

    async def test_unknown_id_returns_404(self, client, admin_headers):
        """A UUID that was never registered returns 404."""
        response = await client.get(
            f"{ADMIN_SUBJECTS_URL}/{uuid.uuid4()}", headers=admin_headers
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_unauthenticated_returns_401(self, client):
        """No token returns 401."""
        response = await client.get(f"{ADMIN_SUBJECTS_URL}/{uuid.uuid4()}")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_field_worker_role_returns_403(self, client, field_worker_headers):
        """A field worker token is rejected on the admin endpoint."""
        response = await client.get(
            f"{ADMIN_SUBJECTS_URL}/{uuid.uuid4()}", headers=field_worker_headers
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
