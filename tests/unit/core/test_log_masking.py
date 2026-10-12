import copy

import pytest

from app.config.log_masking import (
    REDACTED,
    mask_email,
    mask_event_dict,
    mask_text,
    mask_url,
    server_request_hook,
)
from tests.unit.core.helpers import FakeSpan


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
        "access_token",
        "refresh_token",
        "token",
        "token_hash",
        "Authorization",
        "cookie",
        "X-Internal-Token",
        "fcm_token",
        "installation_id",
        "dni",
        "DNI",
        "last_name",
        "lastName",
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
        "jwt_secret_access",
        "jwt_secret_refresh",
        "gemini_api_key",
        "storage_secret_access_key",
        "fcm_private_key",
        "smtp_password",
        "internal_service_token",
        "database_url",
        "rate_limit_redis_url",
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


@pytest.mark.parametrize("sibling", ["last_name", "dni", "email"])
def test_name_is_masked_next_to_a_personal_identifier(sibling):
    assert mask_event_dict({"name": "Ana", sibling: "x"})["name"] == REDACTED


def test_name_is_kept_when_alone():
    assert mask_event_dict({"name": "Comedor Norte", "id": 1}) == {
        "name": "Comedor Norte",
        "id": 1,
    }


def test_ids_route_status_and_birth_date_are_kept():
    event = {
        "event": "request",
        "subject_id": "7d9f",
        "trace_id": "0af7651916cd43dd8448eb211c80319c",
        "level": "info",
        "path": "/api/v1/subjects",
        "status_code": 200,
        "birth_date": "2015-03-01",
        "client_ip": "190.1.2.3",
    }
    assert mask_event_dict(event) == event


def test_nested_dicts_and_lists_are_masked():
    event = {
        "before": {"dni": "123", "tags": ["ok", {"password": "p"}]},
        "rows": ({"email": "a@b.com"},),
    }
    assert mask_event_dict(event) == {
        "before": {"dni": REDACTED, "tags": ["ok", {"password": REDACTED}]},
        "rows": ({"email": "a***@b.com"},),
    }


def test_input_is_not_mutated():
    event = {"dni": "123", "nested": {"password": "p"}, "items": [{"email": "a@b.com"}]}
    original = copy.deepcopy(event)

    mask_event_dict(event)

    assert event == original


def test_text_values_are_masked_by_content():
    masked = mask_event_dict({"error": "failed for juan@dominio.com", "n": 3})
    assert masked == {"error": "failed for j***@dominio.com", "n": 3}


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "GET /subjects?search=Juan&page=2&subject_id=7 HTTP/1.1",
            "GET /subjects?search=[REDACTED]&page=2&subject_id=7 HTTP/1.1",
        ),
        (
            "/users?page=1&Email=a@b.com&name=Ana&last_name=P",
            "/users?page=1&Email=[REDACTED]&name=[REDACTED]&last_name=[REDACTED]",
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


def test_mask_text_is_linear_on_long_unbroken_strings():
    # A quadratic scan would take seconds on this input.
    assert mask_text("a" * 200_000) == "a" * 200_000


def test_mask_url_masks_userinfo_query_and_fragment():
    url = "https://u:p@h.com/x?search=Juan Perez&page=1#access_token=zzz"
    assert mask_url(url) == (
        "https://[REDACTED]@h.com/x?search=[REDACTED]&page=1#access_token=[REDACTED]"
    )


@pytest.mark.parametrize(
    ("attributes", "expected"),
    [
        (
            {"http.url": "http://h/items?search=Tom&Jerry&page=2"},
            {"http.url": "http://h/items?search=[REDACTED]&page=2"},
        ),
        (
            {"url.query": "search=x&page=2"},
            {"url.query": "search=[REDACTED]&page=2"},
        ),
    ],
)
def test_server_request_hook_masks_url_attributes(attributes, expected):
    span = FakeSpan(attributes)

    server_request_hook(span, {"query_string": b"search=Tom%26Jerry&page=2"})

    assert span.attributes == expected
