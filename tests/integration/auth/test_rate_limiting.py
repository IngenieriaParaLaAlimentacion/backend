"""Per-IP rate limits on the public auth endpoints that carry no email.

Run against a real Redis, through the real routes and services.
"""

import asyncio
from uuid import uuid4

import pytest

from app.config.settings import settings

# name -> (url, setting that holds its limit, request body)
IP_ONLY_ENDPOINTS = {
    "register": (
        "/api/v1/auth/register/field-worker",
        "rate_limit_register_ip",
        {
            "email": "rate@test.com",
            "password": "long-enough-1",
            "name": "Ana",
            "last_name": "Gomez",
        },
    ),
    "refresh": (
        "/api/v1/auth/refresh",
        "rate_limit_token_ip",
        {"refresh_token": "unknown", "device_id": str(uuid4())},
    ),
    "password-recovery-confirm": (
        "/api/v1/auth/password-recovery/confirm",
        "rate_limit_token_ip",
        {"token": "unknown", "new_password": "long-enough-1"},
    ),
    "verify-email-confirm": (
        "/api/v1/auth/verify-email/confirm",
        "rate_limit_token_ip",
        {"token": "unknown"},
    ),
}


async def _post(client, name, ip="1.1.1.1"):
    url, _, body = IP_ONLY_ENDPOINTS[name]
    return await client.post(url, json=body, headers={"X-Real-IP": ip})


def _set_limit(monkeypatch, name, value):
    monkeypatch.setattr(settings, IP_ONLY_ENDPOINTS[name][1], value)


@pytest.mark.parametrize("name", IP_ONLY_ENDPOINTS)
async def test_exceeding_the_ip_limit_returns_429(
    client, monkeypatch, connect_limiter_to_redis, name
):
    """Past its limit, an origin gets the standard 429 with the wait time."""
    _set_limit(monkeypatch, name, "2/minute")

    within_limit = [(await _post(client, name)).status_code for _ in range(2)]
    response = await _post(client, name)

    assert 429 not in within_limit
    assert response.status_code == 429
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["type"] == "/errors/rate-limited"
    assert 1 <= int(response.headers["Retry-After"]) <= 60


async def test_retry_after_is_how_long_the_caller_really_waits(
    client, monkeypatch, connect_limiter_to_redis
):
    """Waiting the advertised time is enough to get through again."""
    _set_limit(monkeypatch, "refresh", "1/2second")
    await _post(client, "refresh")
    blocked = await _post(client, "refresh")

    await asyncio.sleep(int(blocked.headers["Retry-After"]))

    assert blocked.status_code == 429
    assert (await _post(client, "refresh")).status_code != 429


async def test_counters_survive_a_backend_restart(
    client, monkeypatch, connect_limiter_to_redis
):
    """The count lives in Redis, so a new connection sees the earlier requests."""
    _set_limit(monkeypatch, "refresh", "2/minute")
    for _ in range(2):
        await _post(client, "refresh")

    connect_limiter_to_redis()

    assert (await _post(client, "refresh")).status_code == 429
