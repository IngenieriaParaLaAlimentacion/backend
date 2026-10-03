# ADR-0019: Rate limiting on public authentication endpoints

- **Status**: Accepted
- **Date**: 2026-09-29
- **Deciders**: Backend team
- **Related**: Issue #162 (Rate Limiting en auth endpoints)

## Context

Login, refresh, password recovery, email verification and registration had no limit. That allows
password guessing by brute force, using the recovery and verification endpoints to send mail to
third parties, and saturating the service. The platform handles data about minors, which raises the
cost of a compromised account.

There is no API gateway in front of the backend, so this service is the only place a limit can be
enforced, both per origin (IP) and per account (email).

The backend runs on Railway behind an edge proxy. Behind it, `request.client.host` is the proxy's
address, not the caller's: a per-IP limit keyed on it would put every user in one bucket.

## Decision

### Library, algorithm and storage

- **`limits`**, using its async API, behind one process-wide limiter. It is built on the first
  request and its connections are closed when the backend shuts down.
- **Moving window**, which avoids the double burst at the boundary of two fixed windows.
- **Redis** as storage, so counters survive restarts and agree across replicas. Short connect and
  socket timeouts (0.2 s) bound how long an outage can delay a request.

### What is limited

Each endpoint has its own counter per IP and, where the body carries an email, a second one per
email.

| Endpoint | Per email | Per IP | Scope |
| --- | --- | --- | --- |
| `POST` login | yes | yes | `login` |
| `POST` password-recovery/request | yes | yes | `mail-sending` (email), own scope (IP) |
| `POST` verify-email/resend | yes | yes | `mail-sending` (email), own scope (IP) |
| `POST` register/field-worker | — | yes | `register` |
| `POST` refresh | — | yes | `refresh` |
| `POST` password-recovery/confirm | — | yes | `password-recovery-confirm` |
| `POST` verify-email/confirm | — | yes | `verify-email-confirm` |

Recovery request and verification resend share one counter per email, because both send mail to the
same person. Separate counters would let an attacker multiply the mail sent to a victim by
alternating between the two endpoints. Their per-IP counters stay separate.

There are no generic limits across the API. A generic per-IP limit would block the field workers
of one establishment, who share an egress IP, and a generic per-email limit would mix login with
recovery.

Limits are written `<count>/<period>` in environment variables and are checked at startup, so a
typo stops the backend instead of leaving an endpoint unprotected. Initial values:

| Profile | Per email | Per IP |
| --- | --- | --- |
| login | 5/minute | 20/minute |
| mail-sending (recovery and resend) | 3/hour | 10/hour |
| refresh, recovery confirm, verify confirm | — | 20/minute |
| register | — | 5/hour |

Per-IP limits are looser because field workers at one establishment share an IP.

### Identifying the caller

- **IP**: the `X-Real-IP` header. Railway's edge proxy sets it to the client address and overwrites
  any value the client sends, and the container is only reachable through that proxy. When the
  header is missing or is not an IP address, the socket address is used. Deployments behind the
  proxy set `RATE_LIMIT_REQUIRE_X_REAL_IP=true`, so a missing header is logged as a warning. The
  environment name cannot tell them apart: a local run and the Railway dev environment are both
  `development`.
- **IPv6** addresses count by their /64 network, because one subscriber controls a whole /64 and
  could otherwise rotate addresses to get around the limit. IPv4-mapped IPv6 addresses count as
  the IPv4 address.
- **Email** is lowercased and trimmed, so `Juan@x.com` and `juan@x.com ` are one account.

### In the routes

Each limit is a FastAPI dependency in the route's `dependencies` list (`limit_by_ip`,
`limit_by_email`), run in the order declared. The email dependency declares the same `data` body
parameter as the route, so the body is parsed once and the email counted is the validated one.

Every request counts, successful or not. The per-IP limit goes first: an origin that is already
blocked cannot use up a victim's attempts. A body that fails validation never reaches the email
counter, but the IP counter still counts it.

### The 429 response

`application/problem+json`, raised as `RateLimitedError` (`/errors/rate-limited`). `Retry-After`
and the `retry_after` body member carry the real reset of the window. `X-RateLimit-*` headers
appear on the 429 only, and each limited endpoint declares the 429 in its OpenAPI `responses`.

### When Redis is down

The limiter keeps a second moving-window limiter on in-memory counters. When Redis fails, the
request that finds it down is counted in memory and the limiter stays in memory mode, so later
requests do not wait on Redis. One request at a time checks whether Redis is back, after 1 s and
then at doubling intervals up to 30 s, and the limiter returns to Redis on its own. The outage and
the recovery are each logged once.

The backend runs as a single instance, so counting in memory is as exact as Redis while the outage
lasts. Counters kept in memory are lost if the backend restarts during an outage, and they are not
carried over to Redis when it returns. If the backend is scaled to several instances, each counts on
its own and the effective limit becomes N times the configured one; this has to be revisited then.

## Consequences

*Positives*

- Protection per account and per origin, from the same service.
- Thresholds change through configuration, with no code change.
- Protection survives a Redis outage.

*Negatives*

- Redis becomes an infrastructure dependency, in compose and in the deploy.
- The origin IP depends on a Railway guarantee, not on anything the backend controls. Moving off
  Railway means revisiting this decision.
- The per-email limit lets an attacker temporarily block a victim's login. A short window keeps the
  damage small.
- A route with a per-email limit must name its body parameter `data`.
- Emails are stored in Redis in plain text, as part of the counter keys, for the length of the
  window. That is deliberate: it shows which accounts are being targeted. Redis holds personal
  data and is treated accordingly.
- Two unrelated clients that share an IPv6 /64 (some mobile carriers and hosting providers) share
  a counter.
- `limits` has no public method to close its Redis client, so closing it at shutdown relies on the
  library's internals and has to be rechecked when it is upgraded.

## Alternatives considered

**slowapi** — rejected. Its Redis client is synchronous, so a slow or dead Redis blocks the event
loop of every request, and its route decorators and fallback depend on internals of the library.
`limits`, which it wraps, offers the same algorithms with an async API.

**Other async libraries (fastapi-limiter, PyrateLimiter, FastAPI-Cap)** — rejected. They change the
algorithm or the key model, and none offers a degraded mode, which would have to be written anyway.

**Fixed-window counter** — rejected in favour of the moving window, because of the double burst at
the window boundary.

**Letting requests through when Redis is down** — rejected. It removes protection from every login
for the length of an outage, on a platform with data about minors.

**Rejecting requests when Redis is down** — rejected. It would make login impossible during an
outage.

**`X-Forwarded-For`, or an allow-list of proxies (`--forwarded-allow-ips`)** — rejected. The proxy
appends to whatever the client sent in `X-Forwarded-For`, so it can be forged, and Railway does not
publish proxy addresses to build an allow-list.

**Generic per-IP or per-email limits across the API** — rejected; see *What is limited*.
