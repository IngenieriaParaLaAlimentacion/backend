import io
import json
import logging
import sys
from typing import NamedTuple

import pytest
import structlog
from opentelemetry.instrumentation.logging.handler import LoggingHandler
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import SimpleLogRecordProcessor

from app.config.log_masking import MaskingLogRecordProcessor
from app.config.logging import setup_logging
from app.config.settings import settings
from tests.unit.core.helpers import SnapshotLogExporter

_UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access", "fastapi")


class OtelLogs(NamedTuple):
    handler: LoggingHandler
    exporter: SnapshotLogExporter


@pytest.fixture
def otel_logs(monkeypatch):
    """A working OTel logging pipeline: masking processor, then a snapshot export."""
    # The suite disables the OTel SDK globally, which turns the logger provider and
    # the logging handler into no-ops, so it is re-enabled while the provider is built.
    monkeypatch.setenv("OTEL_SDK_DISABLED", "false")
    exporter = SnapshotLogExporter()
    provider = LoggerProvider()
    provider.add_log_record_processor(MaskingLogRecordProcessor())
    provider.add_log_record_processor(SimpleLogRecordProcessor(exporter))
    return OtelLogs(LoggingHandler(logger_provider=provider), exporter)


@pytest.fixture
def stdout_logs(monkeypatch, otel_logs):
    """Run the real ``setup_logging`` and return a reader of the JSON lines it prints.

    Root, uvicorn and structlog configuration are restored afterwards.
    """
    monkeypatch.setattr(settings, "environment", "production")
    # The stream handler binds sys.stdout when it is created, so a buffer is
    # installed first instead of relying on the per-phase capture objects.
    buffer = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buffer)
    root = logging.getLogger()
    named = [logging.getLogger(name) for name in _UVICORN_LOGGERS]
    saved_root = (list(root.handlers), root.level)
    saved_named = [(log, list(log.handlers), log.propagate, log.level) for log in named]
    saved_structlog = structlog.get_config()

    setup_logging(otel_handler=otel_logs.handler)
    # A test that starts a real uvicorn server leaves these loggers at CRITICAL for
    # the rest of the process, while a running service has them at INFO.
    for log in named:
        log.setLevel(logging.INFO)

    def read() -> list[dict]:
        lines = buffer.getvalue().splitlines()
        buffer.seek(0)
        buffer.truncate()
        return [json.loads(line) for line in lines if line.strip()]

    yield read

    root.handlers[:], root.level = saved_root[0], saved_root[1]
    for log, handlers, propagate, level in saved_named:
        log.handlers[:], log.propagate = handlers, propagate
        log.setLevel(level)
    structlog.configure(**saved_structlog)
