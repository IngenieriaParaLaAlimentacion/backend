import copy
import uuid
from collections import namedtuple

import pytest
from sqlalchemy import DateTime

from app.config.log_masking import (
    REDACTED,
    mask_email,
    mask_event_dict,
    mask_query_string,
    mask_text,
    mask_url,
)
from app.config.log_masking.core import _is_sensitive_key, normalize_key
from app.config.log_masking.rules import (
    EMAIL_KEY_FRAGMENTS,
    EXACT_KEYS,
    KEY_FRAGMENTS,
    NAME_KEYS,
    QUERY_PARAM_EXACT_KEYS,
)
from app.models import Base


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("juan@dominio.com", "j***@dominio.com"),
        ("Juan.Perez+tag@mail.example.com.ar", "J***@mail.example.com.ar"),
        ("not-an-email", REDACTED),
    ],
)
def test_mask_email_keeps_first_letter_and_domain(value, expected):
    assert mask_email(value) == expected


@pytest.mark.parametrize(
    "key",
    [
        "password",
        "new_password",
        "password_hashed",
        "access_token",
        "refresh_token",
        "token",
        "token_hash",
        "reset_token",
        "invite_token",
        "Authorization",
        "Proxy-Authorization",
        "jwt",
        "session_id",
        "cookie",
        "Set-Cookie",
        "X-Internal-Token",
        "fcm_token",
        "installation_id",
        "dni",
        "last_name",
        "lastName",
        "requester_name",
        "requester_last_name",
        "contact_phone",
        "weight_kg",
        "height_cm",
        "bmi",
        "avg_bmi",
        "IMC",
        "hemoglobin",
        "answers",
        "payload",
        "description",
        "comments",
        "reason",
        "jwt_secret_access",
        "gemini_api_key",
        "storage_secret_access_key",
        "fcm_private_key",
        "smtp_password",
        "internal_service_token",
        "database_url",
        "rate_limit_redis_url",
        "cuil",
        "Telefono",
        "peso_kg",
        "z.score",
        "percentil",
        "sex",
        "is_indigenous",
        "score_fies",
        "full_name",
        "detail",
        "device_name",
        "locality",
    ],
)
def test_sensitive_keys_are_fully_masked(key):
    assert mask_event_dict({key: "value", "other": "kept"}) == {
        key: REDACTED,
        "other": "kept",
    }


@pytest.mark.parametrize("key", ["email", "requester_email", "to_email", "Email"])
def test_email_keys_are_partially_masked(key):
    assert mask_event_dict({key: "juan@dominio.com"}) == {key: "j***@dominio.com"}


@pytest.mark.parametrize("value", [123, None, ["juan@dominio.com"]])
def test_email_key_with_non_string_value_is_fully_masked(value):
    assert mask_event_dict({"email": value}) == {"email": REDACTED}


@pytest.mark.parametrize("name_key", sorted(NAME_KEYS))
@pytest.mark.parametrize("sibling", ["last_name", "email", "description"])
def test_name_is_masked_next_to_a_sensitive_key(name_key, sibling):
    assert mask_event_dict({name_key: "Ana", sibling: "x"})[name_key] == REDACTED


def test_name_is_kept_when_alone():
    assert mask_event_dict({"name": "Comedor Norte", "id": 1}) == {
        "name": "Comedor Norte",
        "id": 1,
    }


def test_keys_and_values_without_sensitive_names_are_kept():
    event = {
        "event": "request",
        "subject_id": "7d9f",
        "submitted_at": "2026-10-15",
        "submitted_by_id": "7d9f",
        "level": "info",
        "path": "/api/v1/subjects",
        "status_code": 200,
    }
    assert mask_event_dict(event) == event


@pytest.mark.parametrize(
    ("event", "expected"),
    [
        ({"tutor_dni": "30123456"}, {"tutor_dni": REDACTED}),
        (
            {"name": "Juan", "birth_date": "2021-03-04"},
            {"name": REDACTED, "birth_date": REDACTED},
        ),
        (
            {"event": "Error guardando DNI 30123456"},
            {"event": f"Error guardando DNI {REDACTED}"},
        ),
        (
            {
                "event": '190.12.34.56:51234 - "GET /children/48213?nombre=Juan '
                'HTTP/1.1" 200'
            },
            {
                "event": f'{REDACTED} - "GET /children/48213?nombre={REDACTED} '
                'HTTP/1.1" 200'
            },
        ),
        # The team decided to keep the partial email mask (first letter and domain).
        ({"user.email": "ana@escuela.edu.ar"}, {"user.email": "a***@escuela.edu.ar"}),
    ],
)
def test_identifiers_in_keys_and_free_text_are_masked(event, expected):
    assert mask_event_dict(event) == expected


def test_nested_dicts_and_lists_are_masked():
    event = {
        "before": {"dni": "123", "tags": ["ok", {"password": "p"}]},
        "rows": ({"email": "a@b.com"},),
    }
    assert mask_event_dict(event) == {
        "before": {"dni": REDACTED, "tags": ["ok", {"password": REDACTED}]},
        "rows": ({"email": "a***@b.com"},),
    }


def test_numbers_booleans_none_and_uuids_pass_through():
    event = {"n": 3, "ratio": 1.5, "ok": True, "missing": None, "id": uuid.uuid4()}

    assert mask_event_dict(event) == event


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (
            Exception("DETAIL: Key (dni)=(30123456) already exists"),
            f"DETAIL:  {REDACTED}",
        ),
        (OSError("refused for ana@dominio.com"), "refused for a***@dominio.com"),
        (b"dni 30123456", f"b'dni {REDACTED}'"),
    ],
)
def test_values_of_other_types_are_masked_as_text(value, expected):
    assert mask_event_dict({"error": value}) == {"error": expected}


def test_namedtuple_is_masked_as_a_plain_tuple():
    Row = namedtuple("Row", ["label", "contact"])

    masked = mask_event_dict({"rows": [Row("a", "ana@dominio.com")]})

    assert masked == {"rows": [("a", "a***@dominio.com")]}


def test_nesting_deeper_than_the_limit_is_redacted():
    event = {}
    node = event
    for _ in range(25):
        node["n"] = {}
        node = node["n"]

    masked = mask_event_dict(event)

    for _ in range(19):
        masked = masked["n"]
    assert masked == {"n": REDACTED}


def test_input_is_not_mutated():
    event = {"dni": "123", "nested": {"password": "p"}, "items": [{"email": "a@b.com"}]}
    original = copy.deepcopy(event)

    mask_event_dict(event)

    assert event == original


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "GET /subjects?search=Juan&page=2&subject_id=7 HTTP/1.1",
            "GET /subjects?search=[REDACTED]&page=2&subject_id=7 HTTP/1.1",
        ),
        (
            "GET /x?filter=30123456&page=2",
            f"GET /x?filter={REDACTED}&page=2",
        ),
        (
            "/users?page=1&Email=a@b.com&name=Ana&last_name=P",
            "/users?page=1&Email=[REDACTED]&name=[REDACTED]&last_name=[REDACTED]",
        ),
        (
            "GET /auth/reset?reset_token=abc123&page=1&invite_token=x",
            "GET /auth/reset?reset_token=[REDACTED]&page=1&invite_token=[REDACTED]",
        ),
        ("contact juan@dominio.com now", "contact j***@dominio.com now"),
        ("Authorization: Bearer abc.def-123_x==", "Authorization: Bearer [REDACTED]"),
        (
            "token eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.c2ln_-x end",
            "token [REDACTED] end",
        ),
        (
            "postgresql+asyncpg://user:pa55@db.internal:5432/app",
            "postgresql+asyncpg://[REDACTED]@db.internal:5432/app",
        ),
        ("CUIL 20-30123456-7 registrado", f"CUIL {REDACTED} registrado"),
        ("from 190.12.34.56 and 10.0.0.1:8080.", f"from {REDACTED} and {REDACTED}."),
        ("DNI 30123456.", f"DNI {REDACTED}."),
        ("DNI 30.123.456 y 1234567", f"DNI {REDACTED} y {REDACTED}"),
        (
            "id 123456 and 123456789 and 9999.99 and 0.12345678",
            "id 123456 and 123456789 and 9999.99 and 0.12345678",
        ),
        (
            "at 2026-10-15T12:34:56.1234567Z and 12345678901234567890123456789012",
            "at 2026-10-15T12:34:56.1234567Z and 12345678901234567890123456789012",
        ),
        (
            "trace 0af7651916cd43dd8448eb211c80319c uuid "
            "12345678-1234-1234-1234-123456789012",
            "trace 0af7651916cd43dd8448eb211c80319c uuid "
            "12345678-1234-1234-1234-123456789012",
        ),
        ("version 1.2.3.4.5 and 1.2.3.456", "version 1.2.3.4.5 and 1.2.3.456"),
        (
            "duplicate key\nDETAIL:  Key (dni)=(12345678) already exists.\n[SQL: x]",
            "duplicate key\nDETAIL:  [REDACTED]\n[SQL: x]",
        ),
        (
            "[SQL: INSERT ... VALUES ($1)]\n[parameters: ('12345678', 'a\nb')]\n"
            "(Background on this error at: https://sqlalche.me/e/20/dbapi)",
            "[SQL: INSERT ... VALUES ($1)]\n[parameters: [REDACTED]]\n"
            "(Background on this error at: https://sqlalche.me/e/20/dbapi)",
        ),
    ],
)
def test_mask_text(text, expected):
    assert mask_text(text) == expected


@pytest.mark.parametrize("char", ["a", "1"])
def test_mask_text_is_linear_on_long_unbroken_strings(char):
    # A quadratic scan would take seconds on this input.
    assert mask_text(char * 200_000) == char * 200_000


def test_mask_url_masks_userinfo_query_and_fragment():
    url = "https://u:p@h.com/x?search=Juan Perez&page=1#access_token=zzz"
    assert mask_url(url) == (
        "https://[REDACTED]@h.com/x?search=[REDACTED]&page=1#access_token=[REDACTED]"
    )


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("filter=30123456&page=2", f"filter={REDACTED}&page=2"),
        ("filter=20-30123456-7", f"filter={REDACTED}"),
        ("from=190.12.34.56", f"from={REDACTED}"),
        ("ref=juan%40mail.com&page=1", f"ref={REDACTED}&page=1"),
        ("ref=juan+perez%40mail.com", f"ref={REDACTED}"),
        ("page=2&order=name", "page=2&order=name"),
    ],
)
def test_query_string_masks_values_by_shape_whatever_the_name(query, expected):
    assert mask_query_string(query) == expected


def test_every_rule_is_stored_normalized():
    rules = KEY_FRAGMENTS | EXACT_KEYS | NAME_KEYS | EMAIL_KEY_FRAGMENTS
    assert all(rule == normalize_key(rule) for rule in rules | QUERY_PARAM_EXACT_KEYS)


# Columns that are neither identifiers nor timestamps and hold no personal data:
# catalog and nutrient data, survey structure, stock quantities, notification
# bookkeeping and establishment data. Adding a column to the schema fails
# `test_every_schema_column_is_masked_or_allowed` until it is masked in `rules.py`
# or listed here on purpose.
NON_SENSITIVE_COLUMNS = frozenset(
    {
        "alerttype",
        "amountper100g",
        "attemptcount",
        "baseunit",
        "category",
        "city",
        "code",
        "deviceid",
        "eventtype",
        "group",
        "instrumenttype",
        "isactive",
        "isrecurring",
        "isrequired",
        "isrural",
        "latitude",
        "longitude",
        "nextthresholdhours",
        "origintype",
        "photokey",
        "placeid",
        "platform",
        "position",
        "province",
        "quantity",
        "requiresresponsenumber",
        "responsecount",
        "responsenumber",
        "responsetarget",
        "responsetype",
        "revoked",
        "role",
        "severity",
        "source",
        "sourcepage",
        "status",
        "text",
        "thresholdhours",
        "unit",
        "used",
    }
)


def test_every_schema_column_is_masked_or_allowed():
    unclassified = {
        f"{table.name}.{column.name}"
        for table in Base.metadata.tables.values()
        for column in table.columns
        if not (
            column.primary_key
            or column.foreign_keys
            or isinstance(column.type, DateTime)
            or _is_sensitive_key(normalize_key(column.name))
            or normalize_key(column.name) in NAME_KEYS
            or normalize_key(column.name) in NON_SENSITIVE_COLUMNS
        )
    }
    assert not unclassified
