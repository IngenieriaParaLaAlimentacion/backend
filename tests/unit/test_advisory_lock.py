from unittest.mock import AsyncMock, MagicMock

import pytest

from app.db.advisory_lock import try_advisory_lock


@pytest.mark.asyncio
async def test_advisory_lock_is_released_before_connection_returns_to_pool():
    connection = MagicMock()
    connection.execution_options = AsyncMock(return_value=connection)
    connection.scalar = AsyncMock(return_value=True)
    connection.execute = AsyncMock()

    connection_context = MagicMock()
    connection_context.__aenter__ = AsyncMock(return_value=connection)
    connection_context.__aexit__ = AsyncMock(return_value=None)
    engine = MagicMock()
    engine.connect.return_value = connection_context

    async with try_advisory_lock(engine, 123) as acquired:
        assert acquired is True

    connection.execute.assert_awaited_once()
    statement, parameters = connection.execute.await_args.args
    assert str(statement) == "SELECT pg_advisory_unlock(:lock_id)"
    assert parameters == {"lock_id": 123}


@pytest.mark.asyncio
async def test_unavailable_advisory_lock_does_not_attempt_unlock():
    connection = MagicMock()
    connection.execution_options = AsyncMock(return_value=connection)
    connection.scalar = AsyncMock(return_value=False)
    connection.execute = AsyncMock()

    connection_context = MagicMock()
    connection_context.__aenter__ = AsyncMock(return_value=connection)
    connection_context.__aexit__ = AsyncMock(return_value=None)
    engine = MagicMock()
    engine.connect.return_value = connection_context

    async with try_advisory_lock(engine, 123) as acquired:
        assert acquired is False

    connection.execute.assert_not_awaited()
