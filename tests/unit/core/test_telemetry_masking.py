import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from opentelemetry import _logs, metrics, trace
from opentelemetry.sdk._logs.export import SimpleLogRecordProcessor
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from app.config import telemetry
from app.config.log_masking import REDACTED
from tests.unit.core.helpers import SnapshotLogExporter


def _emit_library_error(logger: logging.Logger, secret_email: str) -> None:
    try:
        raise OSError(f"refused for {secret_email}")
    except OSError:
        logger.exception("delivery to %s failed", secret_email)


def test_otel_log_body_and_attributes_are_masked(otel_logs):
    logger = logging.getLogger("tests.otel.body")
    logger.addHandler(otel_logs.handler)
    logger.setLevel(logging.INFO)
    try:
        logger.info(
            "request for %s",
            "juan@dominio.com",
            extra={"dni": "12345678", "route": "/subjects"},
        )
    finally:
        logger.removeHandler(otel_logs.handler)

    (exported,) = otel_logs.exporter.records
    assert exported.body == "request for j***@dominio.com"
    assert exported.attributes["dni"] == REDACTED
    assert exported.attributes["route"] == "/subjects"


def test_otel_exception_attributes_are_masked(otel_logs):
    logger = logging.getLogger("tests.otel.exception")
    logger.addHandler(otel_logs.handler)
    try:
        _emit_library_error(logger, "juan@dominio.com")
    finally:
        logger.removeHandler(otel_logs.handler)

    (exported,) = otel_logs.exporter.records
    attributes = exported.attributes
    assert "juan@dominio.com" not in attributes["exception.message"]
    assert "juan@dominio.com" not in attributes["exception.stacktrace"]
    assert attributes["exception.type"] == "OSError"


@pytest.fixture
def wired_telemetry(monkeypatch):
    """``setup_telemetry`` on a fresh app with in-memory exporters."""
    monkeypatch.setenv("OTEL_SDK_DISABLED", "false")
    logs, spans = SnapshotLogExporter(), InMemorySpanExporter()
    monkeypatch.setattr(telemetry, "OTLPLogExporter", lambda: logs)
    monkeypatch.setattr(telemetry, "OTLPSpanExporter", lambda: spans)
    monkeypatch.setattr(telemetry, "OTLPMetricExporter", lambda: None)
    monkeypatch.setattr(telemetry, "BatchLogRecordProcessor", SimpleLogRecordProcessor)
    monkeypatch.setattr(telemetry, "BatchSpanProcessor", SimpleSpanProcessor)
    monkeypatch.setattr(
        telemetry, "PeriodicExportingMetricReader", lambda _: InMemoryMetricReader()
    )
    # Keep the process-wide providers untouched.
    monkeypatch.setattr(trace, "set_tracer_provider", lambda _: None)
    monkeypatch.setattr(metrics, "set_meter_provider", lambda _: None)
    monkeypatch.setattr(_logs, "set_logger_provider", lambda _: None)

    app = FastAPI()

    @app.get("/items")
    def items(search: str = "", page: int = 1) -> dict:
        return {"search": search, "page": page}

    wired = telemetry.setup_telemetry(app)
    yield app, wired, logs, spans
    wired.meter_provider.shutdown()
    wired.tracer_provider.shutdown()
    wired.logger_provider.shutdown()


def test_library_logs_are_masked_before_export(wired_telemetry):
    _, wired, logs, _ = wired_telemetry
    logger = logging.getLogger("tests.telemetry.library")
    logger.addHandler(wired.logging_handler)
    try:
        _emit_library_error(logger, "juan@dominio.com")
    finally:
        logger.removeHandler(wired.logging_handler)

    (exported,) = logs.records
    assert exported.body == "delivery to j***@dominio.com failed"


def test_server_span_url_masks_query_values_and_response_is_unchanged(
    wired_telemetry,
):
    app, _, _, spans = wired_telemetry

    response = TestClient(app).get("/items?search=12345678&page=2")

    assert response.json() == {"search": "12345678", "page": 2}
    (server_span,) = [s for s in spans.get_finished_spans() if s.kind.name == "SERVER"]
    assert server_span.attributes["http.url"].endswith(
        "/items?search=[REDACTED]&page=2"
    )
