import logging
import sys

import structlog
from opentelemetry import trace
from structlog.processors import CallsiteParameter, CallsiteParameterAdder

from app.config.log_masking import mask_structlog_event
from app.config.settings import settings


def add_service_name(logger, log_method, event_dict: dict) -> dict:
    event_dict["service_name"] = settings.service_name
    return event_dict


def opentelemetry_processor(logger, log_method, event_dict: dict) -> dict:
    """
    Enrich log records with OpenTelemetry trace context.

    If there is an active and recording span, this processor adds the
    `trace_id` and `span_id` to the log event dictionary. This enables
    correlation between logs and distributed traces.
    """
    span = trace.get_current_span()
    if not span.is_recording():
        return event_dict
    context = span.get_span_context()
    if context.is_valid:
        event_dict["trace_id"] = trace.format_trace_id(context.trace_id)
        event_dict["span_id"] = trace.format_span_id(context.span_id)
    return event_dict


def setup_logging(otel_handler: logging.Handler | None = None) -> None:
    """
    Configure application structured logging using structlog.

    The configuration ensures consistent, structured, and traceable logs
    across the entire application.
    """
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        CallsiteParameterAdder(
            [
                CallsiteParameter.FILENAME,
                CallsiteParameter.FUNC_NAME,
                CallsiteParameter.LINENO,
            ]
        ),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.ExceptionRenderer(),
        add_service_name,
        opentelemetry_processor,
        mask_structlog_event,
    ]

    if settings.environment == "development":
        processor = structlog.dev.ConsoleRenderer()
    else:
        processor = structlog.processors.JSONRenderer()

    formatter = structlog.stdlib.ProcessorFormatter(
        processor=processor,
        foreign_pre_chain=shared_processors,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)

    if otel_handler:
        root_logger.addHandler(otel_handler)
    root_logger.setLevel(settings.log_level)

    for _log in ("uvicorn", "uvicorn.error", "uvicorn.access", "fastapi"):
        uvicorn_logger = logging.getLogger(_log)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.addHandler(handler)
        if otel_handler:
            uvicorn_logger.addHandler(otel_handler)
        uvicorn_logger.propagate = False

    structlog.configure(
        processors=shared_processors
        + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
