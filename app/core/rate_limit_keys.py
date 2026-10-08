"""Rate-limit keys: who a request is counted against."""

import hmac
import ipaddress

import structlog
from fastapi import Request

from app.config.settings import settings

logger = structlog.get_logger()

# Headers the backoffice sets on every call it forwards.
SERVICE_TOKEN_HEADER = "x-internal-token"
SERVICE_CLIENT_IP_HEADER = "x-client-ip"


def normalize_email(email: str) -> str:
    """Return the email in the canonical form used to build rate-limit keys."""
    return email.strip().lower()


def client_ip(request: Request) -> str:
    """Return the address the request is counted against.

    A request from the backoffice that carries the shared service token is
    counted against the user address it reports in ``X-Client-IP``. Any other
    request is counted against the address in the header named by
    ``RATE_LIMIT_CLIENT_IP_HEADER``, which the edge proxy writes, falling back to
    the socket peer when that header is missing or is not an IP address.
    """
    reported = _reported_by_service(request)
    if reported is not None:
        return reported
    return _edge_address(request)


def _reported_by_service(request: Request) -> str | None:
    """Return the user address a backoffice request reports, if it can be trusted."""
    expected = settings.internal_service_token
    presented = request.headers.get(SERVICE_TOKEN_HEADER)
    if expected is None or presented is None:
        return None
    if not hmac.compare_digest(
        presented.encode(), expected.get_secret_value().encode()
    ):
        return None

    address = _parse_ip(request.headers.get(SERVICE_CLIENT_IP_HEADER))
    if address is None:
        logger.warning("rate_limit.service_client_ip_invalid", path=request.url.path)
    return address


def _edge_address(request: Request) -> str:
    """Return the address the edge proxy reported, or the socket peer."""
    header = settings.rate_limit_client_ip_header
    value = request.headers.get(header)
    if not value:
        # Behind the proxy a missing header means the deploy changed, and the
        # peer address is then the proxy's, so every user would share a counter.
        logger.warning(
            "rate_limit.client_ip_header_missing", header=header, path=request.url.path
        )
        return _peer_host(request)

    address = _parse_ip(value)
    if address is None:
        # The value becomes part of a Redis key, so an arbitrary string would
        # let a caller mint a new counter on every request.
        logger.warning(
            "rate_limit.client_ip_header_invalid", header=header, path=request.url.path
        )
        return _peer_host(request)
    return address


def _parse_ip(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return None


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
