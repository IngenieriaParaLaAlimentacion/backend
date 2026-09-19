from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = structlog.get_logger()


@asynccontextmanager
async def try_advisory_lock(engine: AsyncEngine, lock_id: int) -> AsyncIterator[bool]:
    """Try to hold a PostgreSQL session lock for an asynchronous operation."""
    async with engine.connect() as connection:
        connection = await connection.execution_options(isolation_level="AUTOCOMMIT")
        acquired = bool(
            await connection.scalar(
                text("SELECT pg_try_advisory_lock(:lock_id)"),
                {"lock_id": lock_id},
            )
        )
        try:
            yield acquired
        finally:
            if acquired:
                try:
                    await connection.execute(
                        text("SELECT pg_advisory_unlock(:lock_id)"),
                        {"lock_id": lock_id},
                    )
                except Exception:
                    # A pooled connection must never retain a session-level lock.
                    await connection.invalidate()
                    logger.exception(
                        "Failed to release PostgreSQL advisory lock",
                        lock_id=lock_id,
                    )
