"""Pure masking functions for log events, log text and request URLs."""

import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import unquote_plus
from uuid import UUID

from app.config.log_masking.rules import (
    CLIENT_IP_ATTRIBUTES,
    EMAIL_KEY_FRAGMENTS,
    EXACT_KEYS,
    KEY_FRAGMENTS,
    NAME_KEYS,
    QUERY_PARAM_EXACT_KEYS,
    URL_ATTRIBUTES,
    URL_QUERY_ATTRIBUTE,
)

REDACTED = "[REDACTED]"
MASKING_ERROR = "[masking error]"

_MAX_DEPTH = 20

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

# A number counts as an identifier only when it stands alone: not next to letters
# (trace ids, UUIDs), digits, hyphens (dates, UUID segments) or a dotted
# continuation (decimals, versions). A trailing sentence period is still allowed.
_NUMBER_START = r"(?<![A-Za-z0-9\-])(?<!\d\.)"
_NUMBER_END = r"(?![A-Za-z0-9\-])(?!\.\d)"
_CUIL = re.compile(rf"{_NUMBER_START}\d{{2}}-\d{{8}}-\d{_NUMBER_END}")
_OCTET = r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)"
_IPV4 = re.compile(
    rf"(?<![\d.])(?:{_OCTET}\.){{3}}{_OCTET}(?::\d{{1,5}})?(?!\d)(?!\.\d)"
)
# Any standalone 7-8 digit number is masked, even when it is not a DNI (a byte
# count, a duration in ms). This is intentional: a false positive hides a
# debugging value, a miss leaks the document of a child or a guardian.
_DNI = re.compile(
    rf"{_NUMBER_START}(?:\d{{1,2}}\.\d{{3}}\.\d{{3}}|\d{{7,8}}){_NUMBER_END}"
)
# A query parameter value matching any of these is masked whatever its name.
_VALUE_SHAPES = (_EMAIL, _JWT, _CUIL, _IPV4, _DNI)


def normalize_key(name: str) -> str:
    """Return the key lowercased without ``_``, ``-`` and ``.``."""
    return name.lower().replace("_", "").replace("-", "").replace(".", "")


def _has_fragment(compact: str) -> bool:
    return any(fragment in compact for fragment in KEY_FRAGMENTS)


def _is_email_key(compact: str) -> bool:
    return any(fragment in compact for fragment in EMAIL_KEY_FRAGMENTS)


def is_sensitive_key(compact: str) -> bool:
    """Return whether a normalized key is an exact key or contains a fragment."""
    return compact in EXACT_KEYS or _has_fragment(compact)


def _has_sensitive_sibling(compacts: Mapping[Any, str], key: Any) -> bool:
    return any(
        is_sensitive_key(other)
        for other_key, other in compacts.items()
        if other_key != key
    )


def _is_sensitive_query_param(name: str) -> bool:
    compact = normalize_key(name)
    return compact in QUERY_PARAM_EXACT_KEYS or _has_fragment(compact)


def mask_email(value: str) -> str:
    """Return the address as first letter, ``***`` and the domain.

    A value without an ``@`` is replaced entirely by ``[REDACTED]``.
    """
    local, at, domain = value.rpartition("@")
    if not at:
        return REDACTED
    return f"{local[:1]}***@{domain}"


def _mask_query_param(match: re.Match[str]) -> str:
    # The value is decoded only to detect its shape: `%40` hides the `@` of an email.
    value = unquote_plus(match["value"])
    if _is_sensitive_query_param(match["name"]) or any(
        pattern.search(value) for pattern in _VALUE_SHAPES
    ):
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
    text = _EMAIL.sub(lambda match: mask_email(match[0]), text)
    # CUIL and IPv4 go before DNI: their digit groups would otherwise be
    # consumed by the DNI pattern.
    text = _CUIL.sub(REDACTED, text)
    text = _IPV4.sub(REDACTED, text)
    return _DNI.sub(REDACTED, text)


def mask_query_string(query: str) -> str:
    """Mask the values of sensitive parameters in a query string without ``?``."""
    query = _QUERY_STRING_PARAM.sub(_mask_query_param, query)
    query = _JWT.sub(REDACTED, query)
    return _EMAIL.sub(lambda match: mask_email(match[0]), query)


def mask_span_attributes(
    attributes: Mapping[str, Any], raw_query: str
) -> dict[str, str]:
    """Return the masked values of the URL and client address attributes of a span."""
    # The query comes from the raw ASGI value because the instrumentation
    # URL-decodes the attributes, which makes parameter boundaries ambiguous.
    query = mask_query_string(raw_query)
    masked = {}
    for key in URL_ATTRIBUTES:
        value = attributes.get(key)
        if isinstance(value, str):
            path, question, _ = value.partition("?")
            base = mask_text(path)
            # `http.target` can carry only the path: the query is not added to it.
            masked[key] = f"{base}?{query}" if question and query else base
    if URL_QUERY_ATTRIBUTE in attributes:
        masked[URL_QUERY_ATTRIBUTE] = query
    for key in CLIENT_IP_ATTRIBUTES:
        if key in attributes:
            masked[key] = REDACTED
    return masked


def mask_value(value: Any, depth: int = 0) -> Any:
    """Return the value with sensitive data masked.

    Numbers, booleans, ``None`` and UUIDs pass through. Strings are masked as text,
    dicts, lists and tuples recursively, and any other type by its ``str()``.
    """
    if value is None or isinstance(value, (bool, int, float, UUID)):
        return value
    if isinstance(value, str):
        return mask_text(value)
    if isinstance(value, (Mapping, list, tuple)) and depth >= _MAX_DEPTH:
        return REDACTED
    if isinstance(value, Mapping):
        return _mask_mapping(value, depth)
    if isinstance(value, list):
        return _mask_items(value, depth, list)
    if isinstance(value, tuple):
        return _mask_items(value, depth, tuple)
    # Exceptions, bytes, sets and plain objects reach the renderers through their
    # repr or str, so they are masked as the text they would be written as.
    return mask_text(str(value))


def _mask_items(items: Any, depth: int, container: type) -> Any:
    # The container is built explicitly: a namedtuple cannot be rebuilt from a
    # generator, and its field names are not needed in a log line.
    return container(mask_value(item, depth + 1) for item in items)


def _mask_mapping(mapping: Mapping, depth: int) -> dict:
    compacts = {key: normalize_key(key) for key in mapping if isinstance(key, str)}
    masked = {}
    for key, value in mapping.items():
        compact = compacts.get(key)
        if compact is None:
            masked[key] = mask_value(value, depth + 1)
        elif _is_email_key(compact):
            masked[key] = mask_email(value) if isinstance(value, str) else REDACTED
        elif is_sensitive_key(compact) or (
            compact in NAME_KEYS and _has_sensitive_sibling(compacts, key)
        ):
            masked[key] = REDACTED
        else:
            masked[key] = mask_value(value, depth + 1)
    return masked


def mask_event_dict(event_dict: Mapping) -> dict:
    """Return a copy of the event with sensitive keys and text values masked.

    Nested dicts and lists are masked recursively and the input is never mutated.
    """
    return _mask_mapping(event_dict, 0)
