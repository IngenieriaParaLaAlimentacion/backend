"""Rate limiter shared by the public authentication endpoints."""

import functools
import ipaddress
import time

import structlog
from fastapi import Depends, Request
from fastapi.params import Depends as DependsParam
from limits import RateLimitItem, parse
from limits.aio.strategies import MovingWindowRateLimiter
from limits.errors import StorageError
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


# How long to wait before checking whether a dead Redis is back, doubling after
# each failed check.
_PROBE_MIN_SECONDS = 1.0
_PROBE_MAX_SECONDS = 30.0


class ResilientLimiter:
    """Moving-window limiter that keeps counting in memory while Redis is down.

    Requests go to Redis until it fails. From then on they are counted in this
    process instead, without waiting on Redis, and one request at a time checks
    whether Redis is back, at growing intervals.
    """

    def __init__(
        self, primary: MovingWindowRateLimiter, fallback: MovingWindowRateLimiter
    ):
        self.primary = primary
        self._fallback = fallback
        self._degraded = False
        self._next_probe = 0.0
        self._probe_delay = _PROBE_MIN_SECONDS
        self._probing = False

    async def hit(self, limit: RateLimitItem, *identifiers: str) -> bool:
        """Count a request; return False when it exceeds the limit."""
        return await self._run("hit", limit, identifiers)

    async def get_window_stats(self, limit: RateLimitItem, *identifiers: str):
        """Return the window's remaining quota and reset time."""
        return await self._run("get_window_stats", limit, identifiers)

    async def _run(self, operation: str, limit: RateLimitItem, identifiers: tuple):
        if self._degraded and not await self._redis_is_back():
            return await getattr(self._fallback, operation)(limit, *identifiers)
        try:
            return await getattr(self.primary, operation)(limit, *identifiers)
        except StorageError as exc:
            self._enter_degraded_mode(exc)
            return await getattr(self._fallback, operation)(limit, *identifiers)

    def _enter_degraded_mode(self, exc: Exception) -> None:
        if self._degraded:
            return
        # Counting in memory is exact while the backend is a single instance;
        # with replicas each one would count on its own.
        logger.warning("rate_limit.storage_unreachable", error=repr(exc))
        self._degraded = True
        self._probe_delay = _PROBE_MIN_SECONDS
        self._next_probe = time.monotonic() + self._probe_delay

    async def _redis_is_back(self) -> bool:
        # A single request checks at a time; the rest keep counting in memory
        # instead of queueing behind a Redis that may not answer.
        if self._probing or time.monotonic() < self._next_probe:
            return False
        self._probing = True
        try:
            try:
                healthy = await self.primary.storage.check()
            except StorageError:
                healthy = False
        finally:
            self._probing = False
        if healthy:
            logger.info("rate_limit.storage_recovered")
            self._degraded = False
            return True
        self._probe_delay = min(self._probe_delay * 2, _PROBE_MAX_SECONDS)
        self._next_probe = time.monotonic() + self._probe_delay
        return False


_limiter: ResilientLimiter | None = None


def get_limiter() -> ResilientLimiter:
    """Return the process-wide limiter, creating it on first use."""
    global _limiter
    if _limiter is None:
        redis = storage_from_string(
            f"async+{settings.rate_limit_redis_url}",
            implementation="redispy",
            wrap_exceptions=True,
            socket_connect_timeout=settings.rate_limit_redis_connect_timeout_seconds,
            socket_timeout=settings.rate_limit_redis_socket_timeout_seconds,
        )
        memory = storage_from_string("async+memory://")
        _limiter = ResilientLimiter(
            MovingWindowRateLimiter(redis), MovingWindowRateLimiter(memory)
        )
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
