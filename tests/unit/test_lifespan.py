from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app


def test_lifespan_shutdown_calls_telemetry_and_db_cleanup():
    with (
        patch("app.main.telemetry") as mock_telemetry,
        patch("app.main.engine") as mock_engine,
    ):
        mock_engine.dispose = AsyncMock()

        with TestClient(app):
            pass

        mock_telemetry.tracer_provider.shutdown.assert_called_once()
        mock_telemetry.meter_provider.shutdown.assert_called_once()
        mock_telemetry.logger_provider.shutdown.assert_called_once()
        mock_engine.dispose.assert_awaited_once()


def test_lifespan_logs_error_when_telemetry_shutdown_fails(caplog):
    with (
        patch("app.main.telemetry") as mock_telemetry,
        patch("app.main.engine") as mock_engine,
    ):
        mock_telemetry.tracer_provider.shutdown.side_effect = RuntimeError("boom")
        mock_engine.dispose = AsyncMock()

        with caplog.at_level("ERROR"):
            with TestClient(app):
                pass

        assert "Failed to shutdown tracer_provider" in caplog.text
