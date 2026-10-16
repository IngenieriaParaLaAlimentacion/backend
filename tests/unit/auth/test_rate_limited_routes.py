"""Per-IP rate limits on the public auth endpoints that carry no email."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.config.settings import settings
from app.core.dependencies import get_auth_service
from app.core.rate_limit import close_limiter
from app.exceptions.domain_exceptions import UnauthorizedError
from app.main import app

_REGISTER = {
    "email": "a@x.com",
    "password": "long-enough-1",
    "name": "Ana",
    "last_name": "Gomez",
}

# name -> (url, setting that holds its limit, request body)
IP_ONLY_ENDPOINTS = {
    "register": (
        "/api/v1/auth/register/field-worker",
        "rate_limit_register_ip",
        _REGISTER,
    ),
    "refresh": (
        "/api/v1/auth/refresh",
        "rate_limit_token_ip",
        {"refresh_token": "t", "device_id": str(uuid4())},
    ),
    "password-recovery-confirm": (
        "/api/v1/auth/password-recovery/confirm",
        "rate_limit_token_ip",
        {"token": "t", "new_password": "long-enough-1"},
    ),
    "verify-email-confirm": (
        "/api/v1/auth/verify-email/confirm",
        "rate_limit_token_ip",
        {"token": "t"},
    ),
}


@pytest.fixture
async def client(monkeypatch):
    """Client over the real routes with a service that rejects every call.

    A rejected call still counts against the limit, and it keeps the routes from
    needing a database.
    """
    service = MagicMock()
    for method in (
        "register_field_worker",
        "refresh",
        "confirm_password_recovery",
        "verify_email",
    ):
        setattr(service, method, AsyncMock(side_effect=UnauthorizedError()))
    app.dependency_overrides[get_auth_service] = lambda: service
    for _, setting, _ in IP_ONLY_ENDPOINTS.values():
        monkeypatch.setattr(settings, setting, "2/minute")
    await close_limiter()
    yield TestClient(app)
    app.dependency_overrides.pop(get_auth_service)
    await close_limiter()


def _post(client, name, ip="1.1.1.1"):
    url, _, body = IP_ONLY_ENDPOINTS[name]
    return client.post(url, json=body, headers={"X-Real-IP": ip})


@pytest.mark.parametrize("name", IP_ONLY_ENDPOINTS)
def test_exceeding_the_ip_limit_returns_429(client, name):
    """Each endpoint blocks an origin once it passes its own limit."""
    assert [_post(client, name).status_code for _ in range(2)] == [401, 401]

    response = _post(client, name)

    assert response.status_code == 429
    assert response.json()["type"] == "/errors/rate-limited"


@pytest.mark.parametrize("name", IP_ONLY_ENDPOINTS)
def test_another_ip_is_not_affected(client, name):
    """Only the origin that passed the limit is blocked."""
    for _ in range(3):
        _post(client, name)

    assert _post(client, name, ip="2.2.2.2").status_code == 401


def test_exhausting_one_endpoint_does_not_block_the_others(client):
    """The same IP keeps a separate counter per endpoint."""
    for _ in range(3):
        _post(client, "refresh")

    others = [name for name in IP_ONLY_ENDPOINTS if name != "refresh"]
    assert [_post(client, name).status_code for name in others] == [401] * 3


def test_a_payload_that_fails_validation_still_counts_against_the_ip_limit(client):
    """Invalid bodies cannot be used to probe an endpoint without limit."""
    url, _, body = IP_ONLY_ENDPOINTS["refresh"]
    for _ in range(2):
        assert (
            client.post(url, json={}, headers={"X-Real-IP": "1.1.1.1"}).status_code
            == 422
        )

    assert _post(client, "refresh").status_code == 429


def test_email_limited_routes_name_their_body_parameter_like_the_limit():
    """The email limit reads the body the route already parses.

    A route whose body parameter has another name would make FastAPI expect two
    bodies and answer every request with a 422.
    """
    checked = 0
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        for dep in route.dependant.dependencies:
            if dep.call.__qualname__.startswith("limit_by_email"):
                checked += 1
                route_bodies = {f.name for f in route.dependant.body_params}
                assert {f.name for f in dep.body_params} <= route_bodies, route.path

    assert checked == 3
