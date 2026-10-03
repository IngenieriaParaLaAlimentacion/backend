"""Rate limiting while the counter storage (Redis) is unreachable."""

import asyncio
import time
from uuid import uuid4

import structlog

from app.config.settings import settings

REFRESH_URL = "/api/v1/auth/refresh"


async def _refresh(client, ip="1.1.1.1"):
    body = {"refresh_token": "unknown", "device_id": str(uuid4())}
    return await client.post(REFRESH_URL, json=body, headers={"X-Real-IP": ip})


async def test_the_limit_still_applies_while_redis_is_down(
    client, monkeypatch, connect_limiter_to_redis, redis_outage
):
    """An outage degrades to per-instance counting instead of dropping the limit."""
    monkeypatch.setattr(settings, "rate_limit_token_ip", "2/minute")
    redis_outage.start()

    started = time.monotonic()
    statuses = [(await _refresh(client)).status_code for _ in range(3)]
    elapsed = time.monotonic() - started

    assert 429 not in statuses[:2]
    assert statuses[2] == 429
    # Only the request that finds Redis down waits on a socket timeout.
    assert elapsed < 2


async def test_an_outage_and_its_recovery_are_logged(
    client, monkeypatch, connect_limiter_to_redis, redis_outage
):
    """Operators can see when the limiter left Redis and when it came back."""
    with structlog.testing.capture_logs() as logs:
        redis_outage.start()
        await _refresh(client)
        redis_outage.end()
        await asyncio.sleep(1.2)
        await _refresh(client)

    events = [log["event"] for log in logs]
    assert events.count("rate_limit.storage_unreachable") == 1
    assert events.count("rate_limit.storage_recovered") == 1


async def test_redis_is_used_again_after_the_outage(
    client, monkeypatch, connect_limiter_to_redis, redis_outage
):
    """When Redis returns, counting goes back to it without a restart."""
    monkeypatch.setattr(settings, "rate_limit_token_ip", "2/minute")
    redis_outage.start()
    await _refresh(client)

    redis_outage.end()
    await asyncio.sleep(1.2)
    await _refresh(client)
    await _refresh(client)
    # A new connection sees only what was counted in Redis, not in memory.
    await connect_limiter_to_redis()

    assert (await _refresh(client)).status_code == 429
