"""Masking of sensitive data in log events, log text and request URLs.

The masking core (`mask_email`, `mask_text`, `mask_event_dict`, `mask_url`) is
pure and shared by three adapters: a structlog processor, an OpenTelemetry
``LogRecordProcessor`` and a ``server_request_hook`` for FastAPI spans.
"""

import re
from collections.abc import Mapping
from typing import Any

from opentelemetry.sdk._logs import LogRecordProcessor, ReadWriteLogRecord
from opentelemetry.trace import Span


def _compact(name: str) -> str:
    """Return the key lowercased without ``_`` and ``-``."""
    return name.lower().replace("_", "").replace("-", "")


def _compact_all(*names: str) -> frozenset[str]:
    return frozenset(_compact(name) for name in names)


REDACTED = "[REDACTED]"

_MAX_DEPTH = 20

_URL_ATTRIBUTES = ("http.url", "url.full")

EMAIL_KEYS = _compact_all("email", "requester_email", "to_email")

SENSITIVE_KEYS = EMAIL_KEYS | _compact_all(
    "password",
    "new_password",
    "password_hashed",
    "access_token",
    "refresh_token",
    "token",
    "token_hash",
    "authorization",
    "cookie",
    "x-internal-token",
    "fcm_token",
    "installation_id",
    "gemini_api_key",
    "storage_secret_access_key",
    "fcm_private_key",
    "smtp_password",
    "internal_service_token",
    "database_url",
    "rate_limit_redis_url",
    "dni",
    "last_name",
    "requester_name",
    "requester_last_name",
    "contact_phone",
    "weight_kg",
    "height_cm",
    "bmi",
    "hemoglobin",
    "answers",
    "payload",
    "description",
    "comments",
    "reason",
)

_SECRET_PREFIXES = (_compact("jwt_secret_"),)

_NAME_KEY = "name"
_NAME_SIBLINGS = _compact_all("last_name", "dni", "email")

QUERY_PARAMS = SENSITIVE_KEYS | _compact_all("search", "name")

_URL_USERINFO = re.compile(r"(?<=://)[^/\s:@]+(?::[^/\s@]*)?@")
_BEARER = re.compile(r"\bBearer\s+[A-Za-z0-9\-._~+/]+=*", re.IGNORECASE)
_JWT = re.compile(r"\beyJ[\w-]+\.[\w-]+\.[\w-]*")
_SQL_PARAMETERS = re.compile(
    r"\[parameters: .*?\](?=\s*\(Background on this error|\s*\Z)", re.DOTALL
)
_DB_DETAIL = re.compile(r"\bDETAIL:[ \t]+[^\n]*")
_QUERY_PARAM = re.compile(
    r"(?P<sep>[?&;])(?P<name>[^=&#\s\"']+)=(?P<value>[^&#\s\"']*)"
)
_QUERY_STRING_PARAM = re.compile(r"(?P<sep>^|&)(?P<name>[^=&]+)=(?P<value>[^&]*)")
# The lookbehind makes a match start only at the beginning of a run of address
# characters, which keeps the scan linear on long unbroken strings.
_EMAIL = re.compile(
    r"(?<![A-Za-z0-9._%+\-])[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+"
)


def mask_email(value: str) -> str:
    """Return the address as first letter, ``***`` and the domain.

    A value without an ``@`` is replaced entirely by ``[REDACTED]``.
    """
    local, at, domain = value.rpartition("@")
    if not at:
        return REDACTED
    return f"{local[:1]}***@{domain}"


def _mask_query_param(match: re.Match[str]) -> str:
    if _compact(match["name"]) in QUERY_PARAMS:
        return f"{match['sep']}{match['name']}={REDACTED}"
    return match[0]


def mask_text(text: str) -> str:
    """Mask credentials, personal data and database details inside free text."""
    text = _URL_USERINFO.sub(f"{REDACTED}@", text)
    text = _BEARER.sub(f"Bearer {REDACTED}", text)
    text = _JWT.sub(REDACTED, text)
    text = _SQL_PARAMETERS.sub(f"[parameters: {REDACTED}]", text)
    text = _DB_DETAIL.sub(f"DETAIL:  {REDACTED}", text)
    text = _QUERY_PARAM.sub(_mask_query_param, text)
    return _EMAIL.sub(lambda match: mask_email(match[0]), text)


def mask_query_string(query: str) -> str:
    """Mask the values of sensitive parameters in a query string without ``?``."""
    query = _QUERY_STRING_PARAM.sub(_mask_query_param, query)
    query = _JWT.sub(REDACTED, query)
    return _EMAIL.sub(lambda match: mask_email(match[0]), query)


def mask_url(url: str) -> str:
    """Mask URL userinfo and sensitive query-string and fragment parameters."""
    base, question, rest = url.partition("?")
    query, hash_sign, fragment = rest.partition("#")
    if not question:
        base, hash_sign, fragment = base.partition("#")
    return (
        mask_text(base)
        + question
        + mask_query_string(query)
        + hash_sign
        + mask_query_string(fragment)
    )


def _is_sensitive_key(key: str, siblings: frozenset[str]) -> bool:
    compact = _compact(key)
    if compact in SENSITIVE_KEYS or compact.startswith(_SECRET_PREFIXES):
        return True
    return compact == _NAME_KEY and not siblings.isdisjoint(_NAME_SIBLINGS)


def _mask_value(value: Any, depth: int = 0) -> Any:
    if isinstance(value, str):
        return mask_text(value)
    if depth >= _MAX_DEPTH:
        return REDACTED
    if isinstance(value, Mapping):
        return _mask_mapping(value, depth)
    if isinstance(value, (list, tuple)):
        return type(value)(_mask_value(item, depth + 1) for item in value)
    return value


def _mask_mapping(mapping: Mapping, depth: int) -> dict:
    siblings = frozenset(_compact(key) for key in mapping if isinstance(key, str))
    masked = {}
    for key, value in mapping.items():
        if not isinstance(key, str):
            masked[key] = _mask_value(value, depth + 1)
        elif not _is_sensitive_key(key, siblings):
            masked[key] = _mask_value(value, depth + 1)
        elif _compact(key) in EMAIL_KEYS and isinstance(value, str):
            masked[key] = mask_email(value)
        else:
            masked[key] = REDACTED
    return masked


def mask_event_dict(event_dict: Mapping) -> dict:
    """Return a copy of the event with sensitive keys and text values masked.

    Nested dicts and lists are masked recursively and the input is never mutated.
    """
    return _mask_mapping(event_dict, 0)


def mask_structlog_event(logger: Any, method_name: str, event_dict: dict) -> dict:
    """Structlog processor that masks the whole event dict."""
    return mask_event_dict(event_dict)


class MaskingLogRecordProcessor(LogRecordProcessor):
    """OpenTelemetry log processor that masks the body and attributes in place."""

    def on_emit(self, log_record: ReadWriteLogRecord) -> None:
        """Mask the body and the attributes of the record."""
        record = log_record.log_record
        if record.body is not None:
            record.body = _mask_value(record.body)
        if record.attributes:
            # BoundedAttributes is immutable, so the attributes are replaced
            # with a masked copy instead of being edited.
            record.attributes = mask_event_dict(dict(record.attributes))

    def shutdown(self) -> None:
        """Do nothing: the processor holds no resources."""
        return None

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        """Return True: the processor buffers nothing."""
        return True


def server_request_hook(span: Span, scope: dict) -> None:
    """Mask the query string and userinfo in the URL attributes of a server span."""
    if not span.is_recording():
        return
    # The query is rebuilt from the raw ASGI value because the instrumentation
    # URL-decodes it, which makes parameter boundaries ambiguous.
    query = mask_query_string(scope.get("query_string", b"").decode("latin-1"))
    attributes = span.attributes or {}
    for key in _URL_ATTRIBUTES:
        value = attributes.get(key)
        if isinstance(value, str):
            base = mask_text(value.partition("?")[0])
            span.set_attribute(key, f"{base}?{query}" if query else base)
    if "url.query" in attributes:
        span.set_attribute("url.query", query)
