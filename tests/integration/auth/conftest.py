"""Fixtures for the auth integration tests."""

import pytest
from limits.storage import storage_from_string
from limits.strategies import MovingWindowRateLimiter
from testcontainers.redis import RedisContainer

from app.config.settings import settings
from app.core.rate_limit import limiter


@pytest.fixture(scope="session")
def redis_url():
    """Start a real Redis for the rate-limit tests and return its URL."""
    with RedisContainer("redis:7.4-alpine") as redis:
        host = redis.get_container_host_ip()
        yield f"redis://{host}:{redis.get_exposed_port(6379)}/0"


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

    connect().reset()
    return connect
