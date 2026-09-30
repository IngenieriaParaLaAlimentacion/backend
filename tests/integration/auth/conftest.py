"""Fixtures for the auth integration tests."""

import logging
from types import SimpleNamespace

import pytest
from limits.storage import storage_from_string
from limits.strategies import MovingWindowRateLimiter
from testcontainers.redis import RedisContainer

from app.config.settings import settings
from app.core.rate_limit import limiter


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
def connect_limiter_to_redis(redis_url, monkeypatch):
    """Return a function that points the app's limiter at the test Redis.

    The limiter is built once at import time against ``memory://``, so its
    storage is swapped for the duration of one test. Calling the function again
    opens a fresh connection to the same Redis, as a restarted backend would.
    """

    def connect():
        storage = storage_from_string(
            redis_url,
            socket_connect_timeout=settings.rate_limit_redis_connect_timeout_seconds,
            socket_timeout=settings.rate_limit_redis_socket_timeout_seconds,
        )
        monkeypatch.setattr(limiter, "_storage", storage)
        monkeypatch.setattr(limiter, "_limiter", MovingWindowRateLimiter(storage))
        return storage

    # A test may leave the limiter in degraded mode, or with the backend recheck
    # timers advanced; every test starts from a healthy, freshly checked limiter.
    monkeypatch.setattr(limiter, "_storage_dead", False)
    monkeypatch.setattr(limiter, "_Limiter__check_backend_count", 0)
    monkeypatch.setattr(limiter, "_Limiter__last_check_backend", 0.0)
    limiter._fallback_storage.reset()
    # The app fixture runs the migrations in this process, and alembic's
    # fileConfig disables every logger that already exists, slowapi's included.
    # In production alembic runs in its own process, so its logs are not lost.
    monkeypatch.setattr(logging.getLogger("slowapi"), "disabled", False)
    connect().reset()
    return connect


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
