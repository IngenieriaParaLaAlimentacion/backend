import runpy
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.exc import DBAPIError

from app.db import database
from app.db.database import get_db


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


def test_engine_statement_errors_hide_parameters():
    # Run the module source in isolation: the integration fixtures replace the
    # engine attribute on the imported module.
    engine = runpy.run_path(database.__file__)["engine"]
    error = DBAPIError.instance(
        "INSERT INTO subjects (dni) VALUES ($1)",
        ("12345678",),
        Exception("boom"),
        Exception,
        hide_parameters=engine.sync_engine.hide_parameters,
    )

    assert "12345678" not in str(error)
