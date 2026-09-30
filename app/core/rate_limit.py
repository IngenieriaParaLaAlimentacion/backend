"""Rate limiter shared by the public authentication endpoints."""

import ipaddress
import time
from collections.abc import Awaitable, Callable

import structlog
from fastapi import Request
from slowapi import Limiter

from app.config.settings import settings

logger = structlog.get_logger()

_EMAIL_STATE_ATTR = "rate_limit_email"


def normalize_email(email: str) -> str:
    """Return the email in the canonical form used to build rate-limit keys."""
    return email.strip().lower()


def client_ip(request: Request) -> str:
    """Return the caller's IP address.

    Reads the ``X-Real-IP`` header set by the platform's edge proxy and falls
    back to the socket peer when the header is absent, logging a warning when
    ``RATE_LIMIT_REQUIRE_X_REAL_IP`` is set.
    """
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()

    # Where the backend runs behind the proxy, a request without the header did
    # not come through it, so the peer address is not the caller's and the deploy
    # has changed. The environment name cannot tell this apart from a local run.
    if settings.rate_limit_require_x_real_ip:
        logger.warning("rate_limit.x_real_ip_missing", path=request.url.path)
    return request.client.host if request.client else "unknown"


def ip_bucket(ip: str) -> str:
    """Return the address a rate-limit counter is shared by.

    IPv4 addresses count individually and IPv6 addresses by their /64 network.
    A value that is not an IP address is returned unchanged.
    """
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return ip
    if address.version == 6:
        if address.ipv4_mapped:
            return str(address.ipv4_mapped)
        # A single IPv6 subscriber controls a whole /64, so counting each
        # address on its own would let one client rotate around the limit.
        return str(ipaddress.ip_network(f"{address}/64", strict=False))
    return str(address)


def ip_key(request: Request) -> str:
    """Return the rate-limit key for the caller's IP address."""
    return f"ip:{ip_bucket(client_ip(request))}"


def email_key(request: Request) -> str:
    """Return the rate-limit key for the email captured by ``remember_email``."""
    email = getattr(request.state, _EMAIL_STATE_ATTR, None)
    if email is None:
        # Raising here would make slowapi treat the counter storage as down and
        # switch to its in-memory fallback, so degrade to the IP key instead.
        logger.error("rate_limit.email_missing", path=request.url.path)
        return ip_key(request)
    return f"email:{email}"


def remember_email(body_type: type) -> Callable[..., Awaitable[None]]:
    """Build a dependency that stores the request body's normalized email.

    The dependency shares the ``data`` body parameter with the route, so the
    body is parsed once and the email is the validated one. ``email_key`` reads
    the stored value when the limit is evaluated.
    """

    async def dependency(request: Request, data: body_type) -> None:  # type: ignore[valid-type]
        setattr(request.state, _EMAIL_STATE_ATTR, normalize_email(str(data.email)))

    return dependency


def exceeded_window(request: Request) -> tuple[int, float]:
    """Return the size of the limit just exceeded and when the caller may retry.

    The retry time is epoch seconds: the moment the oldest counted request
    leaves the window.
    """
    limit, identifiers = request.state.view_rate_limit
    try:
        stats = request.app.state.limiter.limiter.get_window_stats(limit, *identifiers)
        return limit.amount, stats.reset_time
    except Exception:
        # The counter storage failed between the hit and this lookup; a whole
        # window is the longest the caller can be asked to wait.
        logger.exception("rate_limit.window_lookup_failed")
        return limit.amount, time.time() + limit.get_expiry()


limiter = Limiter(
    key_func=ip_key,
    strategy="moving-window",
    storage_uri=settings.rate_limit_redis_url,
    storage_options={
        "socket_connect_timeout": settings.rate_limit_redis_connect_timeout_seconds,
        "socket_timeout": settings.rate_limit_redis_socket_timeout_seconds,
    },
    # When the counter storage is unreachable, keep counting in memory per
    # instance rather than disabling the limit or refusing every request.
    in_memory_fallback_enabled=True,
)
