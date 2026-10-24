from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config.settings import settings

# hide_parameters=True keeps bound values (DNI, emails, tokens) out of the text of
# database errors.
engine = create_async_engine(
    settings.database_url,
    hide_parameters=True,
    pool_pre_ping=True,
    pool_size=settings.database_pool_size,
    max_overflow=settings.database_max_overflow,
    connect_args={"timeout": settings.database_connect_timeout_seconds},
)
AsyncSessionLocal = async_sessionmaker(
    engine, expire_on_commit=False, autoflush=False, autocommit=False
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
