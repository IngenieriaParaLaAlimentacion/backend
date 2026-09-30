"""Tests for the rate-limit key rules."""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from slowapi import Limiter

from app.core.rate_limit import email_key, ip_bucket, ip_key, normalize_email
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


def test_email_key_uses_the_email_stored_on_the_request():
    """The per-email key carries the normalized email, not the IP."""
    request = _request()
    request.state.rate_limit_email = "juan@x.com"

    assert email_key(request) == "email:juan@x.com"


def test_email_key_degrades_to_the_ip_key_when_no_email_was_stored():
    """A route that forgot the dependency is still limited, by IP."""
    assert email_key(_request({"x-real-ip": "200.1.2.3"})) == "ip:200.1.2.3"


@pytest.fixture
def limited_client():
    limiter = Limiter(
        key_func=ip_key, strategy="moving-window", storage_uri="memory://"
    )
    app = FastAPI()
    app.state.limiter = limiter
    register_exception_handlers(app)

    @app.post("/limited")
    @limiter.limit("1/minute")
    async def limited(request: Request):
        return {"ok": True}

    return TestClient(app)


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
