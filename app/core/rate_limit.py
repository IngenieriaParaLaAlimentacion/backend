"""Rate limiter shared by the public authentication endpoints."""

import functools
import ipaddress

import structlog
from fastapi import Depends, Request
from fastapi.params import Depends as DependsParam
from limits import RateLimitItem, parse
from limits.aio.strategies import MovingWindowRateLimiter
from limits.storage import storage_from_string

from app.config.settings import settings
from app.exceptions.domain_exceptions import RateLimitedError

logger = structlog.get_logger()

# Recovery and resend send mail to the same person, so both count against one
# per-email counter.
MAIL_SENDING_SCOPE = "mail-sending"


def normalize_email(email: str) -> str:
    """Return the email in the canonical form used to build rate-limit keys."""
    return email.strip().lower()


def client_ip(request: Request) -> str:
    """Return the caller's IP address.

    Reads the ``X-Real-IP`` header set by the platform's edge proxy and falls
    back to the socket peer when the header is absent or is not an IP address,
    logging a warning when ``RATE_LIMIT_REQUIRE_X_REAL_IP`` is set or the header
    is malformed.
    """
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        try:
            return str(ipaddress.ip_address(real_ip.strip()))
        except ValueError:
            # The value becomes part of a Redis key, so an arbitrary string
            # would let a caller mint a new counter on every request.
            logger.warning("rate_limit.x_real_ip_invalid", path=request.url.path)
            return _peer_host(request)

    # Where the backend runs behind the proxy, a request without the header did
    # not come through it, so the peer address is not the caller's and the deploy
    # has changed. The environment name cannot tell this apart from a local run.
    if settings.rate_limit_require_x_real_ip:
        logger.warning("rate_limit.x_real_ip_missing", path=request.url.path)
    return _peer_host(request)


def _peer_host(request: Request) -> str:
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


def email_key(email: str) -> str:
    """Return the rate-limit key for an account's email."""
    return f"email:{normalize_email(email)}"


@functools.cache
def _parse_limit(value: str) -> RateLimitItem:
    return parse(value)


_limiter: MovingWindowRateLimiter | None = None


def get_limiter() -> MovingWindowRateLimiter:
    """Return the process-wide limiter, creating it on first use."""
    global _limiter
    if _limiter is None:
        storage = storage_from_string(
            f"async+{settings.rate_limit_redis_url}",
            implementation="redispy",
            socket_connect_timeout=settings.rate_limit_redis_connect_timeout_seconds,
            socket_timeout=settings.rate_limit_redis_socket_timeout_seconds,
        )
        _limiter = MovingWindowRateLimiter(storage)
    return _limiter


def reset_limiter() -> None:
    """Drop the limiter so the next request builds a fresh one with empty counters."""
    global _limiter
    _limiter = None


async def _enforce(setting: str, scope: str, key: str) -> None:
    """Count a request against a limit and raise ``RateLimitedError`` past it."""
    limit = _parse_limit(getattr(settings, setting))
    limiter = get_limiter()
    if await limiter.hit(limit, scope, key):
        return
    stats = await limiter.get_window_stats(limit, scope, key)
    raise RateLimitedError(limit.amount, stats.reset_time)


def limit_by_ip(setting: str, scope: str) -> DependsParam:
    """Build a route dependency that limits the caller's IP address.

    ``setting`` names the settings attribute holding the limit. The counter is
    private to ``scope``.
    """

    async def dependency(request: Request) -> None:
        await _enforce(setting, scope, ip_key(request))

    return Depends(dependency)


def limit_by_email(body_type: type, setting: str, scope: str) -> DependsParam:
    """Build a route dependency that limits the account named in the body.

    The dependency shares the ``data`` body parameter with the route, so the body
    is parsed once and the email is the validated one.
    """

    async def dependency(data: body_type) -> None:  # type: ignore[valid-type]
        await _enforce(setting, scope, email_key(str(data.email)))

    return Depends(dependency)
