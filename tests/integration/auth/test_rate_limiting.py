"""Per-IP rate limits on the public auth endpoints that carry no email.

Run against a real Redis, through the real routes and services.
"""

import asyncio
from uuid import uuid4

import pytest

from app.config.settings import settings

# name -> (url, setting that holds its limit, request body)
IP_ONLY_ENDPOINTS = {
    "register": (
        "/api/v1/auth/register/field-worker",
        "rate_limit_register_ip",
        {
            "email": "rate@test.com",
            "password": "long-enough-1",
            "name": "Ana",
            "last_name": "Gomez",
        },
    ),
    "refresh": (
        "/api/v1/auth/refresh",
        "rate_limit_token_ip",
        {"refresh_token": "unknown", "device_id": str(uuid4())},
    ),
    "password-recovery-confirm": (
        "/api/v1/auth/password-recovery/confirm",
        "rate_limit_token_ip",
        {"token": "unknown", "new_password": "long-enough-1"},
    ),
    "verify-email-confirm": (
        "/api/v1/auth/verify-email/confirm",
        "rate_limit_token_ip",
        {"token": "unknown"},
    ),
}


async def _post(client, name, ip="1.1.1.1"):
    url, _, body = IP_ONLY_ENDPOINTS[name]
    return await client.post(url, json=body, headers={"X-Real-IP": ip})


def _set_limit(monkeypatch, name, value):
    monkeypatch.setattr(settings, IP_ONLY_ENDPOINTS[name][1], value)


@pytest.mark.parametrize("name", IP_ONLY_ENDPOINTS)
async def test_exceeding_the_ip_limit_returns_429(
    client, monkeypatch, connect_limiter_to_redis, name
):
    """Past its limit, an origin gets the standard 429 with the wait time."""
    _set_limit(monkeypatch, name, "2/minute")

    within_limit = [(await _post(client, name)).status_code for _ in range(2)]
    response = await _post(client, name)

    assert 429 not in within_limit
    assert response.status_code == 429
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["type"] == "/errors/rate-limited"
    assert 1 <= int(response.headers["Retry-After"]) <= 60


async def test_retry_after_is_how_long_the_caller_really_waits(
    client, monkeypatch, connect_limiter_to_redis
):
    """Waiting the advertised time is enough to get through again."""
    _set_limit(monkeypatch, "refresh", "1/2second")
    await _post(client, "refresh")
    blocked = await _post(client, "refresh")

    await asyncio.sleep(int(blocked.headers["Retry-After"]))

    assert blocked.status_code == 429
    assert (await _post(client, "refresh")).status_code != 429


async def test_counters_survive_a_backend_restart(
    client, monkeypatch, connect_limiter_to_redis
):
    """The count lives in Redis, so a new connection sees the earlier requests."""
    _set_limit(monkeypatch, "refresh", "2/minute")
    for _ in range(2):
        await _post(client, "refresh")

    await connect_limiter_to_redis()

    assert (await _post(client, "refresh")).status_code == 429


# -- Endpoints limited by email and by IP ------------------------------------

# name -> (url, request body builder)
EMAIL_ENDPOINTS = {
    "login": (
        "/api/v1/auth/login",
        lambda email: {"email": email, "password": "x", "device_id": str(uuid4())},
    ),
    "password-recovery-request": (
        "/api/v1/auth/password-recovery/request",
        lambda email: {"email": email},
    ),
    "verify-email-resend": (
        "/api/v1/auth/verify-email/resend",
        lambda email: {"email": email},
    ),
}


async def _post_email(client, name, email, ip="1.1.1.1"):
    url, body = EMAIL_ENDPOINTS[name]
    return await client.post(url, json=body(email), headers={"X-Real-IP": ip})


def _set_limits(monkeypatch, **limits):
    for setting, value in limits.items():
        monkeypatch.setattr(settings, f"rate_limit_{setting}", value)


# Which settings hold each endpoint's email and IP limit.
_LIMIT_SETTINGS = {
    "login": ("login_email", "login_ip"),
    "password-recovery-request": ("mail_sending_email", "mail_sending_ip"),
    "verify-email-resend": ("mail_sending_email", "mail_sending_ip"),
}


@pytest.mark.parametrize("name", EMAIL_ENDPOINTS)
async def test_email_limit_holds_across_origins(
    client, monkeypatch, connect_limiter_to_redis, name
):
    """An account is limited no matter how many IPs the attempts come from."""
    email_setting, _ = _LIMIT_SETTINGS[name]
    _set_limits(monkeypatch, **{email_setting: "2/minute"})

    first = [
        (await _post_email(client, name, "victim@x.com", ip=f"9.9.9.{i}")).status_code
        for i in range(2)
    ]
    blocked = await _post_email(client, name, "victim@x.com", ip="9.9.9.99")
    other_account = await _post_email(client, name, "other@x.com", ip="9.9.9.99")

    assert 429 not in first
    assert blocked.status_code == 429
    assert blocked.json()["type"] == "/errors/rate-limited"
    assert other_account.status_code != 429


@pytest.mark.parametrize("name", EMAIL_ENDPOINTS)
async def test_ip_limit_holds_across_accounts(
    client, monkeypatch, connect_limiter_to_redis, name
):
    """One origin trying many accounts is stopped."""
    _, ip_setting = _LIMIT_SETTINGS[name]
    _set_limits(monkeypatch, **{ip_setting: "2/minute"})

    first = [
        (await _post_email(client, name, f"user{i}@x.com")).status_code
        for i in range(2)
    ]
    blocked = await _post_email(client, name, "user3@x.com")

    assert 429 not in first
    assert blocked.status_code == 429


async def test_email_variants_count_as_the_same_account(
    client, monkeypatch, connect_limiter_to_redis
):
    """Case and surrounding whitespace do not open a fresh counter."""
    _set_limits(monkeypatch, login_email="2/minute")

    await _post_email(client, "login", "Juan@x.com")
    await _post_email(client, "login", "JUAN@X.COM")

    assert (await _post_email(client, "login", "juan@x.com")).status_code == 429


async def test_recovery_and_resend_share_the_email_counter(
    client, monkeypatch, connect_limiter_to_redis
):
    """Alternating between the two mail endpoints does not multiply the mail."""
    _set_limits(monkeypatch, mail_sending_email="2/minute")

    await _post_email(client, "password-recovery-request", "victim@x.com")
    await _post_email(client, "verify-email-resend", "victim@x.com")

    assert (
        await _post_email(client, "password-recovery-request", "victim@x.com")
    ).status_code == 429
    assert (
        await _post_email(client, "verify-email-resend", "victim@x.com")
    ).status_code == 429


async def test_exhausting_login_does_not_block_password_recovery(
    client, monkeypatch, connect_limiter_to_redis
):
    """The same email and IP keep a separate counter per endpoint."""
    _set_limits(monkeypatch, login_email="1/minute", login_ip="1/minute")
    await _post_email(client, "login", "a@x.com")
    assert (await _post_email(client, "login", "a@x.com")).status_code == 429

    response = await _post_email(client, "password-recovery-request", "a@x.com")

    assert response.status_code != 429


async def test_mail_endpoints_keep_their_own_ip_counter(
    client, monkeypatch, connect_limiter_to_redis
):
    """Only the email counter is shared between recovery and resend."""
    _set_limits(monkeypatch, mail_sending_ip="1/minute")
    await _post_email(client, "password-recovery-request", "a@x.com")
    assert (
        await _post_email(client, "password-recovery-request", "b@x.com")
    ).status_code == 429

    response = await _post_email(client, "verify-email-resend", "c@x.com")

    assert response.status_code != 429


async def test_a_request_blocked_by_ip_does_not_use_the_account_counter(
    client, monkeypatch, connect_limiter_to_redis
):
    """An origin that is already blocked cannot burn a victim's attempts."""
    _set_limits(monkeypatch, login_ip="1/minute", login_email="2/minute")
    await _post_email(client, "login", "victim@x.com", ip="1.1.1.1")
    blocked = await _post_email(client, "login", "victim@x.com", ip="1.1.1.1")

    # One attempt of the account's two is used; a different origin still gets one.
    other_origin = await _post_email(client, "login", "victim@x.com", ip="2.2.2.2")

    assert blocked.status_code == 429
    assert other_origin.status_code != 429
