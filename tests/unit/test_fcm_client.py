from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest
from google.auth.exceptions import RefreshError

from app.services.notifications.fcm_client import FcmClient, FcmOutcome


def _client() -> FcmClient:
    client = object.__new__(FcmClient)
    client.project_id = "project"
    client.timeout_seconds = 3.0
    client.credentials = SimpleNamespace(valid=True, token="access")
    return client


@pytest.mark.asyncio
async def test_send_uses_exact_visible_cross_platform_contract():
    response = SimpleNamespace(status_code=200)
    post = AsyncMock(return_value=response)
    http_client = AsyncMock()
    http_client.__aenter__.return_value.post = post
    with patch("app.services.notifications.fcm_client.httpx.AsyncClient") as factory:
        factory.return_value = http_client
        result = await _client().send(
            token="device-token",
            title="Title",
            body="Body",
            data={"stale_days": "7"},
            collapse_key="stale-establishment:e1",
        )

    assert result.outcome == FcmOutcome.SUCCESS
    payload = post.await_args.kwargs["json"]["message"]
    assert payload["data"] == {"stale_days": "7"}
    assert payload["android"] == {
        "collapse_key": "stale-establishment:e1",
        "notification": {
            "channel_id": "stale_establishments",
            "tag": "stale-establishment:e1",
        },
    }
    assert payload["apns"]["headers"]["apns-collapse-id"] == ("stale-establishment:e1")


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [408, 429, 500, 502, 503, 504])
async def test_retryable_statuses_are_transient(status):
    response = SimpleNamespace(status_code=status, json=lambda: {})
    http_client = AsyncMock()
    http_client.__aenter__.return_value.post = AsyncMock(return_value=response)
    with patch(
        "app.services.notifications.fcm_client.httpx.AsyncClient",
        return_value=http_client,
    ):
        result = await _client().send(
            token="t", title="t", body="b", data={}, collapse_key="c"
        )
    assert result.outcome == FcmOutcome.TRANSIENT


@pytest.mark.asyncio
async def test_network_failure_is_transient():
    http_client = AsyncMock()
    http_client.__aenter__.return_value.post = AsyncMock(
        side_effect=httpx.ConnectError("down")
    )
    with patch(
        "app.services.notifications.fcm_client.httpx.AsyncClient",
        return_value=http_client,
    ):
        result = await _client().send(
            token="t", title="t", body="b", data={}, collapse_key="c"
        )
    assert result.outcome == FcmOutcome.TRANSIENT


@pytest.mark.asyncio
async def test_access_token_refreshes_expired_credentials():
    client = _client()
    credentials = SimpleNamespace(valid=False, token=None)

    def refresh(_request):
        credentials.valid = True
        credentials.token = "refreshed-access"

    credentials.refresh = Mock(side_effect=refresh)
    client.credentials = credentials

    assert await client._access_token() == "refreshed-access"
    credentials.refresh.assert_called_once()


@pytest.mark.asyncio
async def test_credential_refresh_failure_is_transient():
    client = _client()
    client.credentials = SimpleNamespace(
        valid=False,
        token=None,
        refresh=Mock(side_effect=RefreshError("refresh failed")),
    )
    result = await client.send(
        token="t", title="t", body="b", data={}, collapse_key="c"
    )
    assert result.outcome == FcmOutcome.TRANSIENT


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "body", "outcome"),
    [
        (
            404,
            {"error": {"details": [{"errorCode": "UNREGISTERED"}]}},
            FcmOutcome.PERMANENT_TOKEN,
        ),
        (400, {"error": {"details": []}}, FcmOutcome.PERMANENT_MESSAGE),
        (401, {}, FcmOutcome.TRANSIENT),
    ],
)
async def test_provider_error_classification(status, body, outcome):
    response = SimpleNamespace(status_code=status, json=lambda: body)
    http_client = AsyncMock()
    http_client.__aenter__.return_value.post = AsyncMock(return_value=response)
    with patch(
        "app.services.notifications.fcm_client.httpx.AsyncClient",
        return_value=http_client,
    ):
        result = await _client().send(
            token="t", title="t", body="b", data={}, collapse_key="c"
        )
    assert result.outcome == outcome


@pytest.mark.asyncio
async def test_non_object_error_body_is_a_permanent_message_failure():
    response = SimpleNamespace(status_code=400, json=lambda: [])
    http_client = AsyncMock()
    http_client.__aenter__.return_value.post = AsyncMock(return_value=response)
    with patch(
        "app.services.notifications.fcm_client.httpx.AsyncClient",
        return_value=http_client,
    ):
        result = await _client().send(
            token="t", title="t", body="b", data={}, collapse_key="c"
        )
    assert result.outcome == FcmOutcome.PERMANENT_MESSAGE


def test_only_token_specific_invalid_argument_evicts_token():
    token_body = {
        "error": {
            "details": [
                {
                    "errorCode": "INVALID_ARGUMENT",
                    "fieldViolations": [{"field": "message.token"}],
                }
            ]
        }
    }
    payload_body = {
        "error": {"details": [{"fieldViolations": [{"field": "message.data"}]}]}
    }
    assert FcmClient._fcm_error_code(token_body) == "INVALID_ARGUMENT"
    assert FcmClient._invalid_token_field(token_body) is True
    assert FcmClient._invalid_token_field(payload_body) is False
