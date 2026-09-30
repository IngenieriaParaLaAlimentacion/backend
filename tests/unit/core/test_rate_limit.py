"""Tests for the rate-limit key rules."""

from types import SimpleNamespace

import pytest
import structlog
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.config.settings import settings
from app.core.rate_limit import (
    client_ip,
    email_key,
    ip_bucket,
    ip_key,
    limit_by_email,
    limit_by_ip,
    normalize_email,
    reset_limiter,
)
from app.exceptions.exception_handlers import register_exception_handlers


def _request(headers: dict[str, str] | None = None, client_host: str = "10.0.0.1"):
    return SimpleNamespace(
        headers=headers or {},
        client=SimpleNamespace(host=client_host),
        state=SimpleNamespace(),
        url=SimpleNamespace(path="/auth/login"),
    )


@pytest.mark.parametrize(
    "variant", ["Juan@x.com", "juan@x.com ", " JUAN@X.COM", "\tjuan@x.com\n"]
)
def test_email_variants_normalize_to_the_same_key(variant):
    """Case and surrounding whitespace do not create a new counter."""
    assert normalize_email(variant) == "juan@x.com"


def test_ip_key_uses_the_edge_proxy_header_over_the_socket_peer():
    """The caller's IP comes from X-Real-IP, not from the proxy's own address."""
    request = _request({"x-real-ip": "200.1.2.3"}, client_host="10.0.0.1")

    assert ip_key(request) == "ip:200.1.2.3"


@pytest.mark.parametrize(
    ("ip", "bucket"),
    [
        ("200.1.2.3", "200.1.2.3"),
        ("2001:db8:1:2:aaaa:bbbb:cccc:dddd", "2001:db8:1:2::/64"),
        ("2001:db8:1:2:1111:2222:3333:4444", "2001:db8:1:2::/64"),
        ("2001:db8:1:3::1", "2001:db8:1:3::/64"),
        ("::ffff:200.1.2.3", "200.1.2.3"),
    ],
)
def test_ip_bucket_groups_ipv6_by_its_64_network(ip, bucket):
    """Addresses of one IPv6 subscriber share a counter; IPv4 ones do not."""
    assert ip_bucket(ip) == bucket


def test_ip_key_falls_back_to_the_socket_peer_without_the_header():
    """Local runs and tests have no proxy, so the peer address is used."""
    assert ip_key(_request()) == "ip:10.0.0.1"


@pytest.mark.parametrize(
    "value", ["not-an-ip", "1.2.3.4, 5.6.7.8", "a" * 5000, "1.2.3.4:80"]
)
def test_a_malformed_x_real_ip_is_ignored_and_logged(value):
    """A header that is not an IP address cannot mint its own counter."""
    with structlog.testing.capture_logs() as logs:
        key = ip_key(_request({"x-real-ip": value}, client_host="10.0.0.1"))

    assert key == "ip:10.0.0.1"
    assert [log["event"] for log in logs] == ["rate_limit.x_real_ip_invalid"]


def test_x_real_ip_is_trimmed_and_normalized():
    """Surrounding whitespace and spelling variants map to one counter."""
    assert client_ip(_request({"x-real-ip": " 2001:DB8::1 "})) == "2001:db8::1"


@pytest.mark.parametrize(("require_header", "warns"), [(True, True), (False, False)])
def test_missing_x_real_ip_warns_only_where_a_proxy_is_expected(
    monkeypatch, require_header, warns
):
    """A local run stays quiet; a deploy behind the proxy is told it lost the header."""
    monkeypatch.setattr(settings, "rate_limit_require_x_real_ip", require_header)

    with structlog.testing.capture_logs() as logs:
        client_ip(_request())

    assert bool(logs) is warns


def test_email_key_carries_the_normalized_email():
    """The per-email key is built from the canonical email, not the IP."""
    assert email_key(" Juan@X.com ") == "email:juan@x.com"


class _Body(BaseModel):
    email: str


@pytest.fixture
def limited_client(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_login_ip", "1/minute")
    monkeypatch.setattr(settings, "rate_limit_login_email", "1/minute")
    reset_limiter()
    app = FastAPI()
    register_exception_handlers(app)

    @app.post("/limited", dependencies=[limit_by_ip("rate_limit_login_ip", "test")])
    async def limited():
        return {"ok": True}

    @app.post(
        "/by-email",
        dependencies=[limit_by_email(_Body, "rate_limit_login_email", "test-email")],
    )
    async def by_email(data: _Body):
        return {"ok": True}

    yield TestClient(app)
    reset_limiter()


def test_exceeding_the_limit_returns_429_problem_with_the_wait_time(limited_client):
    """The 429 uses the standard error envelope and says how long to wait."""
    assert limited_client.post("/limited").status_code == 200

    response = limited_client.post("/limited")

    assert response.status_code == 429
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert body["type"] == "/errors/rate-limited"
    assert body["instance"] == "/limited"
    # A 1/minute window cannot ask the caller to wait longer than a minute.
    assert 1 <= body["retry_after"] <= 60
    assert response.headers["Retry-After"] == str(body["retry_after"])


def test_rate_limit_headers_appear_only_on_the_429(limited_client):
    """Successful responses carry no X-RateLimit headers; the 429 does."""
    ok = limited_client.post("/limited")
    blocked = limited_client.post("/limited")

    assert not [h for h in ok.headers if h.lower().startswith("x-ratelimit")]
    assert blocked.headers["X-RateLimit-Limit"] == "1"
    assert blocked.headers["X-RateLimit-Remaining"] == "0"


def test_a_body_that_fails_validation_never_reaches_the_email_counter(limited_client):
    """An invalid payload is answered by validation, not counted against an account."""
    for _ in range(3):
        assert limited_client.post("/by-email", json={}).status_code == 422

    assert (
        limited_client.post("/by-email", json={"email": "a@x.com"}).status_code == 200
    )


def test_the_email_limit_counts_variants_of_one_address_together(limited_client):
    """Case and whitespace do not open a fresh counter."""
    assert (
        limited_client.post("/by-email", json={"email": "A@x.com"}).status_code == 200
    )

    response = limited_client.post("/by-email", json={"email": " a@X.com "})

    assert response.status_code == 429
