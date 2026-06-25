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

os.environ["TESTCONTAINERS_RYUK_DISABLED"] = "true"

LOGIN_URL = "/api/v1/auth/login"


async def make_token_for_role(domain_role) -> str:
    """Create a real DB user for the given role and return a signed access token."""
    from app.core.security import create_access_token
    from app.db.database import AsyncSessionLocal
    from app.models.user import User, UserStatus
    from app.models.user import UserRole as ORMUserRole

    user_id = uuid.uuid4()
    async with AsyncSessionLocal() as session:
        session.add(
            User(
                id=user_id,
                name="Test",
                last_name=domain_role.value.title(),
                email=f"{user_id}@test.com",
                role=ORMUserRole(domain_role.value),
                status=UserStatus.ACTIVE,
            )
        )
        await session.commit()
    return create_access_token(user_id, role=domain_role)


@pytest.fixture
def auth_headers():
    from app.core.security import create_access_token
    from app.domain.user import UserRole

    token = create_access_token(uuid.uuid4(), role=UserRole.ADMIN)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin_headers():
    from app.core.security import create_access_token
    from app.domain.user import UserRole

    token = create_access_token(uuid.uuid4(), role=UserRole.ADMIN)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def manager_headers():
    from app.core.security import create_access_token
    from app.domain.user import UserRole

    token = create_access_token(uuid.uuid4(), role=UserRole.ESTABLISHMENT_MANAGER)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def analyst_headers():
    from app.core.security import create_access_token
    from app.domain.user import UserRole

    token = create_access_token(uuid.uuid4(), role=UserRole.ANALYST)
    return {"Authorization": f"Bearer {token}"}


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

    from app.core.config import settings

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
    from app.models.base import Base

    async with engine.begin() as conn:
        tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
        await conn.execute(text(f"TRUNCATE TABLE {tables} CASCADE"))

    yield


@pytest_asyncio.fixture()
async def db_establishment():
    """Insert a real Establishment row and return the ORM instance."""
    from app.db.database import AsyncSessionLocal
    from app.models.establishment import Establishment

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
async def db_active_user(db_establishment):
    """Insert an active ADMIN user with a known password and return the ORM instance."""
    from app.core.security import hash_password
    from app.db.database import AsyncSessionLocal
    from app.domain.user import UserRole, UserStatus
    from app.models.user import User
    from app.models.user_password import UserPassword

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
    """Insert a PENDING_VALIDATION establishment manager with a known password."""
    from app.core.security import hash_password
    from app.db.database import AsyncSessionLocal
    from app.domain.user import UserRole, UserStatus
    from app.models.user import User
    from app.models.user_password import UserPassword

    async with AsyncSessionLocal() as session:
        user = User(
            name="Pedro",
            last_name="Pending",
            email="pending@test.com",
            role=UserRole.ESTABLISHMENT_MANAGER,
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
