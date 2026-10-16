"""Tests for the limiter's degraded mode while Redis is unreachable."""

import asyncio

import pytest
import structlog
from limits import parse
from limits.aio.strategies import MovingWindowRateLimiter
from limits.errors import StorageError
from limits.storage import storage_from_string

from app.core import rate_limit
from app.core.rate_limit import ResilientLimiter

LIMIT = parse("2/minute")


class FakeRedis:
    """Stands in for the Redis-backed limiter; ``up`` switches it on and off."""

    def __init__(self):
        self.up = True
        self.hits = 0
        self.checks = 0
        self.storage = self

    async def hit(self, limit, *identifiers):
        self.hits += 1
        self._fail_if_down()
        return True

    async def get_window_stats(self, limit, *identifiers):
        self._fail_if_down()

    async def check(self):
        self.checks += 1
        await asyncio.sleep(0)
        return self.up

    def _fail_if_down(self):
        if not self.up:
            raise StorageError(ConnectionError("redis is down"))


@pytest.fixture
def clock(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(rate_limit.time, "monotonic", lambda: now[0])
    return now


@pytest.fixture
def redis():
    return FakeRedis()


@pytest.fixture
def limiter(redis, clock):
    memory = MovingWindowRateLimiter(storage_from_string("async+memory://"))
    return ResilientLimiter(redis, memory)


async def test_the_limit_still_applies_once_redis_fails(limiter, redis):
    """The request that finds Redis down is counted in memory, not let through."""
    redis.up = False

    results = [await limiter.hit(LIMIT, "s", "k") for _ in range(3)]

    assert results == [True, True, False]


async def test_a_dead_redis_is_not_called_before_the_next_check(limiter, redis, clock):
    """Requests during an outage go straight to memory without waiting on Redis."""
    redis.up = False
    await limiter.hit(LIMIT, "s", "k")
    calls = redis.hits

    clock[0] += 0.5
    await limiter.hit(LIMIT, "s", "k")

    assert redis.hits == calls
    assert redis.checks == 0


async def test_redis_is_used_again_once_it_answers_the_check(limiter, redis, clock):
    """The limiter goes back to Redis without a restart."""
    redis.up = False
    await limiter.hit(LIMIT, "s", "k")
    redis.up = True
    clock[0] += 1.1
    hits_before = redis.hits

    with structlog.testing.capture_logs() as logs:
        await limiter.hit(LIMIT, "s", "k")

    assert redis.hits == hits_before + 1
    assert [log["event"] for log in logs] == ["rate_limit.storage_recovered"]


async def test_the_outage_is_logged_once(limiter, redis):
    """A burst of requests during an outage does not repeat the warning."""
    redis.up = False

    with structlog.testing.capture_logs() as logs:
        for _ in range(5):
            await limiter.hit(LIMIT, "s", "k")

    assert [log["event"] for log in logs] == ["rate_limit.storage_unreachable"]


async def test_failed_checks_space_out_up_to_the_maximum(limiter, redis, clock):
    """A Redis that stays down is checked less and less often."""
    redis.up = False
    await limiter.hit(LIMIT, "s", "k")
    waits = []
    for _ in range(8):
        before = redis.checks
        clock[0] += 0.1
        # Advance until the limiter decides to check again.
        elapsed = 0.0
        while redis.checks == before:
            await limiter.hit(LIMIT, "s", "k")
            clock[0] += 0.5
            elapsed += 0.5
        waits.append(elapsed)

    assert waits == sorted(waits)
    assert waits[-1] <= rate_limit._PROBE_MAX_SECONDS + 1


async def test_only_one_request_checks_redis_at_a_time(limiter, redis, clock):
    """Concurrent requests during an outage do not all wait on Redis."""
    redis.up = False
    await limiter.hit(LIMIT, "s", "k")
    clock[0] += 1.1

    await asyncio.gather(*(limiter.hit(LIMIT, "s", "k") for _ in range(10)))

    assert redis.checks == 1


async def test_window_stats_fall_back_when_redis_fails_after_the_hit(limiter, redis):
    """A 429 can still say when to retry if Redis dies between hit and lookup."""
    await limiter.hit(LIMIT, "s", "k")
    redis.up = False

    stats = await limiter.get_window_stats(LIMIT, "s", "k")

    assert stats.reset_time > 0
