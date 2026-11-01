"""Fixtures for the auth integration tests."""

from types import SimpleNamespace

import pytest
from testcontainers.community.redis import RedisContainer

from app.config.settings import settings
from app.core.rate_limit import close_limiter, get_limiter


@pytest.fixture(scope="session")
def redis_container():
    """Start a real Redis for the rate-limit tests."""
    with RedisContainer("redis:7.4-alpine") as redis:
        yield redis


@pytest.fixture(scope="session")
def redis_url(redis_container):
    """Return the URL of the test Redis."""
    host = redis_container.get_container_host_ip()
    return f"redis://{host}:{redis_container.get_exposed_port(6379)}/0"


@pytest.fixture
async def connect_limiter_to_redis(redis_container, redis_url, monkeypatch):
    """Return a function that points the app's limiter at the test Redis.

    The limiter is built on first use from ``RATE_LIMIT_REDIS_URL``. Awaiting the
    function again closes it, so the next request opens a fresh connection to the
    same Redis, as a restarted backend would.
    """
    monkeypatch.setattr(settings, "rate_limit_redis_url", redis_url)

    async def connect():
        await close_limiter()
        return get_limiter()

    redis_container.get_client().flushdb()
    await connect()
    yield connect
    await close_limiter()


@pytest.fixture
async def fresh_limiter():
    """Start the test with no limiter, so the first request builds one from settings.

    The limiter built during the test is dropped afterwards.
    """
    await close_limiter()
    yield
    await close_limiter()


@pytest.fixture
def redis_outage(redis_container):
    """Freeze Redis on demand so connections time out, as in a network outage.

    Pausing the container keeps the port open but stops any reply, which is the
    case that costs a client its full socket timeout. Redis is always resumed on
    teardown.
    """
    container = redis_container.get_wrapped_container()
    state = SimpleNamespace(paused=False)

    def start():
        container.pause()
        state.paused = True

    def end():
        container.unpause()
        state.paused = False

    yield SimpleNamespace(start=start, end=end)
    if state.paused:
        container.unpause()
