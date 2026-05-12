from unittest.mock import AsyncMock, MagicMock

import pytest

from app.db.database import get_db


@pytest.mark.asyncio
async def test_get_db_yields_session(monkeypatch):
    mock_session = MagicMock()
    mock_context_manager = AsyncMock()
    mock_context_manager.__aenter__ = AsyncMock(return_value=mock_session)
    mock_context_manager.__aexit__ = AsyncMock(return_value=False)

    monkeypatch.setattr(
        "app.db.database.AsyncSessionLocal", lambda: mock_context_manager
    )

    gen = get_db()
    session = await gen.__anext__()
    assert session is mock_session
    try:
        await gen.__anext__()
    except StopAsyncIteration:
        pass
    mock_context_manager.__aexit__.assert_called_once()


@pytest.mark.asyncio
async def test_get_db_closes_on_exception(monkeypatch):
    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=MagicMock())
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    monkeypatch.setattr("app.db.database.AsyncSessionLocal", lambda: mock_cm)

    gen = get_db()
    await gen.__anext__()
    try:
        await gen.athrow(RuntimeError("boom"))
    except RuntimeError:
        pass
    mock_cm.__aexit__.assert_called_once()
