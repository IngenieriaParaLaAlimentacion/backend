"""Rate limits for authentication and authenticated AI operations."""

import functools
import time

import structlog
from fastapi import Depends, Request
from fastapi.params import Depends as DependsParam
from limits import RateLimitItem, parse
from limits.aio.strategies import MovingWindowRateLimiter
from limits.errors import StorageError
from limits.storage import storage_from_string

from app.config.settings import settings
from app.core.rate_limit_keys import email_key, ip_key
from app.exceptions.domain_exceptions import RateLimitedError

logger = structlog.get_logger()

# Recovery and resend send mail to the same person, so both count against one
# per-email counter.
MAIL_SENDING_SCOPE = "mail-sending"

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
        self._primary = primary
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

    async def close(self) -> None:
        """Close the connections to Redis, if the primary storage has any."""
        # ``limits`` exposes no close method; the client lives on its bridge, which
        # a ``memory://`` primary storage does not have.
        bridge = getattr(self._primary.storage, "bridge", None)
        if bridge is not None:
            await bridge.storage.aclose()

    async def _run(self, operation: str, limit: RateLimitItem, identifiers: tuple):
        if self._degraded and not await self._redis_is_back():
            return await getattr(self._fallback, operation)(limit, *identifiers)
        try:
            return await getattr(self._primary, operation)(limit, *identifiers)
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
            healthy = await self._primary.storage.check()
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


async def close_limiter() -> None:
    """Close the limiter's Redis connections and drop it.

    The next call to ``get_limiter`` builds a fresh one with empty counters.
    """
    global _limiter
    limiter, _limiter = _limiter, None
    if limiter is not None:
        await limiter.close()


@functools.cache
def _parse_limit(value: str) -> RateLimitItem:
    return parse(value)


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

    ``body_type`` is the route's request model, which must declare ``email``.
    """

    # Declaring the same ``data`` parameter as the route makes FastAPI parse the
    # body once, so the email counted is the validated one.
    async def dependency(data: body_type) -> None:  # type: ignore[valid-type]
        await _enforce(setting, scope, email_key(str(data.email)))

    return Depends(dependency)


def limit_by_user(setting: str, scope: str) -> DependsParam:
    """Count verified actor IDs, so shared IPs do not share an AI quota."""
    from app.core.dependencies import require_any
    from app.domain.user import UserActor

    async def dependency(actor: UserActor = Depends(require_any)) -> None:
        await _enforce(setting, scope, f"user:{actor.user_id}")

    return Depends(dependency)
