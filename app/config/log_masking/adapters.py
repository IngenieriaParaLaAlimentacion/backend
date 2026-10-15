"""Hooks that apply the masking core to structlog, OpenTelemetry logs and spans.

None of them lets an exception escape: when masking fails, the data is replaced
by ``[masking error]`` instead of being passed on unmasked.
"""

from typing import Any

from opentelemetry.sdk._logs import LogRecordProcessor, ReadWriteLogRecord
from opentelemetry.trace import Span

from app.config.log_masking.core import (
    MASKING_ERROR,
    mask_event_dict,
    mask_span_url_attributes,
    mask_value,
)
from app.config.log_masking.rules import URL_ATTRIBUTES, URL_QUERY_ATTRIBUTE

# structlog's ProcessorFormatter deletes these keys right after the processor
# chain and raises KeyError if they are missing, which would drop the log line.
_STRUCTLOG_META_KEYS = ("_record", "_from_structlog")


def mask_structlog_event(logger: Any, method_name: str, event_dict: dict) -> dict:
    """Structlog processor that masks the whole event dict."""
    try:
        return mask_event_dict(event_dict)
    except Exception:
        failed = {"event": MASKING_ERROR, "level": event_dict.get("level")}
        failed.update(
            {key: event_dict[key] for key in _STRUCTLOG_META_KEYS if key in event_dict}
        )
        return failed


class MaskingLogRecordProcessor(LogRecordProcessor):
    """OpenTelemetry log processor that masks the body and attributes in place."""

    def on_emit(self, log_record: ReadWriteLogRecord) -> None:
        """Mask the body and the attributes of the record."""
        record = log_record.log_record
        try:
            if record.body is not None:
                record.body = mask_value(record.body)
            if record.attributes:
                # BoundedAttributes is immutable, so the attributes are replaced
                # with a masked copy instead of being edited.
                record.attributes = mask_event_dict(dict(record.attributes))
        except Exception:
            record.body = MASKING_ERROR
            record.attributes = {}

    def shutdown(self) -> None:
        """Do nothing: the processor holds no resources."""
        return None

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        """Return True: the processor buffers nothing."""
        return True


def server_request_hook(span: Span, scope: dict) -> None:
    """Mask the query string and userinfo in the URL attributes of a server span."""
    try:
        if not span.is_recording():
            return
        raw_query = scope.get("query_string", b"").decode("latin-1")
        masked = mask_span_url_attributes(span.attributes or {}, raw_query)
        for key, value in masked.items():
            span.set_attribute(key, value)
    except Exception:
        _redact_url_attributes(span)


def _redact_url_attributes(span: Span) -> None:
    try:
        for key in (*URL_ATTRIBUTES, URL_QUERY_ATTRIBUTE):
            span.set_attribute(key, MASKING_ERROR)
    except Exception:
        # Nothing is left to do, and the hook must never break the request.
        pass
