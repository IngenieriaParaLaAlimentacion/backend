"""Masking of sensitive data in log events, log text and request URLs.

``rules`` lists which keys are masked, ``core`` holds the pure masking functions
and ``adapters`` plugs them into structlog and OpenTelemetry.
"""

from app.config.log_masking.adapters import (
    MaskingLogRecordProcessor,
    mask_structlog_event,
    server_request_hook,
)
from app.config.log_masking.core import (
    MASKING_ERROR,
    REDACTED,
    mask_email,
    mask_event_dict,
    mask_query_string,
    mask_text,
)

__all__ = [
    "MASKING_ERROR",
    "REDACTED",
    "MaskingLogRecordProcessor",
    "mask_email",
    "mask_event_dict",
    "mask_query_string",
    "mask_structlog_event",
    "mask_text",
    "server_request_hook",
]
