"""Liveness and readiness probes, with the database up and down."""

import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

HEALTH_URL = "/health"
READY_URL = "/ready"

# Nothing listens on port 1, so every connection attempt fails.
_UNREACHABLE_DB_HOST = "127.0.0.1"
_UNREACHABLE_DB_PASSWORD = "probe-s3cr3t"
_UNREACHABLE_DB_URL = (
    f"postgresql+asyncpg://probe:{_UNREACHABLE_DB_PASSWORD}"
    f"@{_UNREACHABLE_DB_HOST}:1/probe"
)


@pytest_asyncio.fixture()
async def unreachable_db(monkeypatch):
    """Point every new session at a database that refuses connections."""
    import app.db.database as db_module
    from app.config.settings import settings

    engine = create_async_engine(_UNREACHABLE_DB_URL)
    monkeypatch.setattr(db_module, "AsyncSessionLocal", async_sessionmaker(engine))
    monkeypatch.setattr(settings, "readiness_db_timeout_seconds", 1)
    yield
    await engine.dispose()


async def test_health_returns_200_with_database_down(client, unreachable_db):
    response = await client.get(HEALTH_URL)

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_ready_returns_200_when_database_answers(client):
    response = await client.get(READY_URL)

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "checks": {"database": "ok"}}


async def test_ready_returns_503_naming_the_failed_check(client, unreachable_db):
    response = await client.get(READY_URL)

    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["type"] == "/errors/service-not-ready"
    assert body["checks"] == {"database": "unavailable"}
    # The probe is public: the connection details behind the failure stay in logs.
    assert _UNREACHABLE_DB_HOST not in response.text
    assert _UNREACHABLE_DB_PASSWORD not in response.text
