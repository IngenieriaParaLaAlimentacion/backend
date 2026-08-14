import os
import uuid

import pytest
import pytest_asyncio
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from testcontainers.postgres import PostgresContainer

from alembic import command
from app.core.security import create_access_token, hash_password
from app.domain.establishment import UserEstablishmentStatus
from app.domain.user import UserRole, UserStatus
from app.models.base import Base
from app.models.establishment import Establishment
from app.models.user import User
from app.models.user_establishment import UserEstablishment
from app.models.user_password import UserPassword

os.environ["TESTCONTAINERS_RYUK_DISABLED"] = "true"

LOGIN_URL = "/api/v1/auth/login"

# --- Auth: tokens and headers ---------------------------------------------


async def _insert_user_with_role(role: UserRole) -> uuid.UUID:
    """Insert a real, ACTIVE DB user for the given role and return its id."""
    from app.db.database import AsyncSessionLocal

    user_id = uuid.uuid4()
    async with AsyncSessionLocal() as session:
        session.add(
            User(
                id=user_id,
                name="Test",
                last_name=role.value.title(),
                email=f"{user_id}@test.com",
                role=role,
                status=UserStatus.ACTIVE,
            )
        )
        await session.commit()
    return user_id


async def make_token_for_role(role: UserRole) -> str:
    """Create a real DB user for the given role and return a signed access token."""
    user_id = await _insert_user_with_role(role)
    return create_access_token(user_id, role=role)


@pytest_asyncio.fixture()
async def make_user_with_role():
    """Factory fixture: create a real DB user with the given role and return
    ``(headers, user_id)``. Used by tests that need several distinct authors/
    actors (e.g. one per role) in the same run.
    """

    async def _make(role: UserRole) -> tuple[dict, uuid.UUID]:
        user_id = await _insert_user_with_role(role)
        token = create_access_token(user_id, role=role)
        return {"Authorization": f"Bearer {token}"}, user_id

    return _make


@pytest.fixture
def admin_headers():
    token = create_access_token(uuid.uuid4(), role=UserRole.ADMIN)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def field_worker_headers():
    token = create_access_token(uuid.uuid4(), role=UserRole.FIELD_WORKER)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def analyst_headers():
    token = create_access_token(uuid.uuid4(), role=UserRole.ANALYST)
    return {"Authorization": f"Bearer {token}"}


# --- Test app and database infrastructure ----------------------------------


@pytest.fixture(scope="session")
def postgres_url():
    """Start a Postgres container for the test session and yield its connection URL."""
    with PostgresContainer("postgres:16-alpine") as postgres:
        yield postgres.get_connection_url()


@pytest.fixture(scope="session")
def app(postgres_url):
    """
    Build the FastAPI app against the test database.

    Patches settings.database_url temporarily so alembic/env.py picks up the
    test container URL, then overrides the DB engine with NullPool. Does NOT
    touch os.environ or sys.modules so unit test module references stay valid.
    """
    sync_url = postgres_url.replace("postgresql+psycopg2://", "postgresql://")
    asyncpg_url = sync_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    from app.config.settings import settings

    original_db_url = settings.database_url
    settings.database_url = asyncpg_url
    try:
        alembic_cfg = Config("alembic.ini")
        command.upgrade(alembic_cfg, "head")
    finally:
        settings.database_url = original_db_url

    import app.db.database as db_module
    from app.main import app as fastapi_app

    db_module.engine = create_async_engine(asyncpg_url, poolclass=NullPool)
    db_module.AsyncSessionLocal = async_sessionmaker(
        db_module.engine, expire_on_commit=False, autoflush=False, autocommit=False
    )

    return fastapi_app


@pytest_asyncio.fixture()
async def client(app):
    """Provide an async HTTP client pointed at the test app."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as async_client:
        yield async_client


@pytest_asyncio.fixture(autouse=True)
async def clean_db(app):
    """Truncate all tables before each test to guarantee isolation."""
    from app.db.database import engine

    async with engine.begin() as conn:
        tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
        await conn.execute(text(f"TRUNCATE TABLE {tables} CASCADE"))

    yield


# --- Domain data fixtures ---------------------------------------------------


@pytest_asyncio.fixture()
async def db_establishment():
    """Insert a real Establishment row and return the ORM instance."""
    from app.db.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        establishment = Establishment(
            name="Centro Test",
            formatted_address="Calle Test 123",
            latitude=-34.6037,
            longitude=-58.3816,
            place_id="place-test-001",
            city="Buenos Aires",
            province="Buenos Aires",
        )
        session.add(establishment)
        await session.commit()
        await session.refresh(establishment)
        return establishment


@pytest_asyncio.fixture()
async def make_field_worker_with_access():
    """Factory fixture: create a field worker with an APPROVED relation to a
    given establishment.

    Returns a callable ``(establishment_id) -> (headers, user_id)``, so a
    single test can create field workers scoped to different establishments.
    """
    from app.db.database import AsyncSessionLocal

    async def _make(establishment_id: uuid.UUID):
        user_id = uuid.uuid4()
        async with AsyncSessionLocal() as session:
            session.add(
                User(
                    id=user_id,
                    name="Maria",
                    last_name="Field Worker",
                    email=f"{user_id}@test.com",
                    role=UserRole.FIELD_WORKER,
                    status=UserStatus.ACTIVE,
                )
            )
            session.add(
                UserEstablishment(
                    user_id=user_id,
                    establishment_id=establishment_id,
                    status=UserEstablishmentStatus.APPROVED,
                )
            )
            await session.commit()

        token = create_access_token(user_id, role=UserRole.FIELD_WORKER)
        return {"Authorization": f"Bearer {token}"}, user_id

    return _make


@pytest_asyncio.fixture()
async def field_worker_with_access(db_establishment, make_field_worker_with_access):
    """Create a field worker with an APPROVED relation to db_establishment.

    Returns (headers, user_id).
    """
    return await make_field_worker_with_access(db_establishment.id)


@pytest_asyncio.fixture()
async def db_active_user(db_establishment):
    """Insert an active ADMIN user with a known password and return the ORM instance."""
    from app.db.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        user = User(
            name="Ana",
            last_name="Gomez",
            email="ana@test.com",
            role=UserRole.ADMIN,
            status=UserStatus.ACTIVE,
        )
        session.add(user)
        await session.flush()
        session.add(
            UserPassword(
                user_id=user.id,
                password_hashed=hash_password("correct_password"),
            )
        )
        await session.commit()
        await session.refresh(user)
        return user


@pytest_asyncio.fixture()
async def db_pending_user():
    """Insert a PENDING_VALIDATION field worker with a known password."""
    from app.db.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        user = User(
            name="Pedro",
            last_name="Pending",
            email="pending@test.com",
            role=UserRole.FIELD_WORKER,
            status=UserStatus.PENDING_VALIDATION,
        )
        session.add(user)
        await session.flush()
        session.add(
            UserPassword(
                user_id=user.id,
                password_hashed=hash_password("correct_password"),
            )
        )
        await session.commit()
        await session.refresh(user)
        return user


@pytest_asyncio.fixture()
async def db_logged_in_user(db_active_user, client):
    """Return (user, refresh_token, device_id) for an already-logged-in active user."""
    device_id = str(uuid.uuid4())
    response = await client.post(
        LOGIN_URL,
        json={
            "email": "ana@test.com",
            "password": "correct_password",
            "device_id": device_id,
        },
    )
    body = response.json()
    return db_active_user, body["refresh_token"], device_id
