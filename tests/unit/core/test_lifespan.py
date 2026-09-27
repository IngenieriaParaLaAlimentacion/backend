from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app


def test_lifespan_shutdown_calls_telemetry_and_db_cleanup():
    with (
        patch("app.main.telemetry") as mock_telemetry,
        patch("app.main.engine") as mock_engine,
        patch("app.main.StaleEstablishmentScheduler") as scheduler_class,
    ):
        mock_engine.dispose = AsyncMock()
        scheduler_class.return_value.shutdown = AsyncMock()

        with TestClient(app):
            scheduler_class.return_value.start.assert_called_once_with()

        scheduler_class.return_value.shutdown.assert_awaited_once_with()
        mock_telemetry.tracer_provider.shutdown.assert_called_once()
        mock_telemetry.meter_provider.shutdown.assert_called_once()
        mock_telemetry.logger_provider.shutdown.assert_called_once()
        mock_engine.dispose.assert_awaited_once()


def test_lifespan_logs_error_when_telemetry_shutdown_fails(caplog):
    with (
        patch("app.main.telemetry") as mock_telemetry,
        patch("app.main.engine") as mock_engine,
        patch("app.main.StaleEstablishmentScheduler") as scheduler_class,
    ):
        mock_telemetry.tracer_provider.shutdown.side_effect = RuntimeError("boom")
        mock_engine.dispose = AsyncMock()
        scheduler_class.return_value.shutdown = AsyncMock()

        with caplog.at_level("ERROR"):
            with TestClient(app):
                pass

        assert "Failed to shutdown tracer_provider" in caplog.text
