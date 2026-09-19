from unittest.mock import AsyncMock, patch

import pytest

from app.config.settings import settings
from app.core.dependencies import get_stale_establishment_notification_service

pytestmark = pytest.mark.asyncio

URL = "/api/v1/internal/stale-establishment-notifications/run"


class RecordingService:
    def __init__(self):
        self.run = AsyncMock()


@pytest.fixture
def recording_service(app):
    service = RecordingService()
    app.dependency_overrides[get_stale_establishment_notification_service] = lambda: (
        service
    )
    yield service
    app.dependency_overrides.pop(get_stale_establishment_notification_service, None)


async def test_internal_route_rejects_missing_and_wrong_secret(
    client, recording_service
):
    with patch.object(settings, "stale_notifications_cron_secret", "expected"):
        missing = await client.post(URL)
        wrong = await client.post(URL, headers={"X-Internal-Secret": "wrong"})

    for response in (missing, wrong):
        assert response.status_code == 401
        assert response.headers["content-type"].startswith("application/problem+json")
        assert response.json()["type"] == "/errors/internal-authentication-failed"
    recording_service.run.assert_not_awaited()


async def test_internal_route_accepts_exact_secret_without_user_jwt(
    client, recording_service
):
    with patch.object(settings, "stale_notifications_cron_secret", "expected"):
        response = await client.post(URL, headers={"X-Internal-Secret": "expected"})

    assert response.status_code == 204
    assert response.content == b""
    recording_service.run.assert_awaited_once_with()


async def test_internal_route_returns_canonical_503_when_not_configured(client, app):
    app.dependency_overrides.pop(get_stale_establishment_notification_service, None)
    with (
        patch.object(settings, "stale_notifications_cron_secret", "expected"),
        patch.object(settings, "stale_notifications_feature_activated_at", None),
        patch.object(settings, "fcm_project_id", None),
        patch.object(settings, "fcm_client_email", None),
        patch.object(settings, "fcm_private_key", None),
    ):
        response = await client.post(URL, headers={"X-Internal-Secret": "expected"})

    assert response.status_code == 503
    assert response.json()["type"] == "/errors/notification-configuration-invalid"
