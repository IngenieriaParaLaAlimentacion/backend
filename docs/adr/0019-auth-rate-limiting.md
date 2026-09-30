# ADR-0019: Rate limiting on public authentication endpoints

- **Status**: Accepted
- **Date**: 2026-09-29
- **Deciders**: Backend team
- **Related**: Issue #162 (Rate Limiting en auth endpoints)

## Context

Login, refresh, password recovery, email verification and registration have no limit today. Three
abuses follow: password guessing by brute force, using the recovery and verification endpoints to
send mail to third parties, and saturating the service with abusive requests. The platform handles
data about minors, which raises the cost of a compromised account.

There is no API gateway in front of the backend, so this service is the only place a limit can be
enforced. Both layers — per origin (IP) and per account (email) — live here.

The backend is deployed on Railway, which terminates traffic at an edge proxy. Behind it,
`request.client.host` is the proxy's address, not the caller's. A per-IP limit keyed on it would put
the whole platform in one bucket.

## Decision

### Tool and storage

- **`limits`** (its async API, `limits.aio`), behind one process-wide limiter built on first use.
  slowapi was tried first and dropped: its Redis client is synchronous, so an unresponsive Redis
  blocks the event loop of the whole service, not just the limited endpoints.
- **Redis** as storage, so counters survive restarts and are consistent across replicas. One
  instance and one `RATE_LIMIT_REDIS_*` configuration; nothing else in the stack uses Redis, so no
  database separation is needed. Redis is added to `compose.yml` and to the Railway deploy.
- The Redis client uses short connect and socket timeouts (0.2 s), so that an outage costs the
  request that finds it a bounded wait before the fallback below takes over. The waiting is
  asynchronous and does not stall other requests.

### Algorithm

`MovingWindowRateLimiter`, which avoids the double burst at the boundary of two fixed windows. It
is one line in the limiter's construction, so reverting to fixed-window touches nothing else.

### Dimensions and scopes

Every endpoint has its own bucket per IP and, where the body carries an email, a second one per
email. The buckets are independent. Keys are `{scope}:ip:{ip}` and `{scope}:email:{email}`.

| Endpoint | Per email | Per IP | Scope |
| --- | --- | --- | --- |
| `POST` login | yes | yes | `login` |
| `POST` password-recovery/request | yes | yes | `mail-sending` (email), own scope (IP) |
| `POST` verify-email/resend | yes | yes | `mail-sending` (email), own scope (IP) |
| `POST` register/field-worker | — | yes | `register` |
| `POST` refresh | — | yes | `refresh` |
| `POST` password-recovery/confirm | — | yes | `password-recovery-confirm` |
| `POST` verify-email/confirm | — | yes | `verify-email-confirm` |

Recovery request and verification resend share one bucket per email (`scope="mail-sending"`, via
`shared_limit`). Their per-IP buckets stay separate, one per endpoint, like every other scope. Both send mail to the same person, so separate buckets would let an attacker
multiply the mail sent to a victim by alternating between the two endpoints.

There are **no generic limits**, per IP or per email, across the API:

- With this few endpoints the total ceiling is already low.
- A generic per-IP limit would block several field workers at one establishment who share an egress
  IP.
- A generic per-email limit would mix login with recovery and could lock out a legitimate user.

Protecting the whole API by IP is a separate story, with thresholds designed for NAT.

### Identifying the origin

The IP comes from the `X-Real-IP` header, not from `request.client.host` and not from
`X-Forwarded-For`.

- Railway's edge proxy sets `X-Real-IP` to the remote client address on every HTTP request and
  overwrites any value the client sends. The container is not reachable except through that proxy.
  Together those two facts make the header non-spoofable. `X-Forwarded-For` is not: the proxy
  appends to whatever the client sent.
- Railway does not publish a stable CIDR for its proxies, so a "trusted proxies" allow-list, such as
  uvicorn's `--forwarded-allow-ips`, cannot be configured. Reading the header directly in the
  `key_func` makes the source of the IP explicit.
- When the header is absent (local development, tests) the key falls back to
  `request.client.host`. Where the backend runs behind the proxy that should not happen, so the
  fallback is logged as a warning rather than taken silently. Those deployments say so with
  `RATE_LIMIT_REQUIRE_X_REAL_IP=true` (Railway dev and prod). The environment name is not used:
  a local run and the Railway dev environment are both `development`, and only one has a proxy.

This trust rests on a platform guarantee. Moving off Railway means revisiting this decision.

IPv4 addresses are counted individually. IPv6 addresses are counted by their /64 network, because
a single subscriber controls a whole /64 and could otherwise rotate addresses to get around the
limit; IPv4-mapped IPv6 addresses count as the IPv4 address.

The email is normalised (lowercased, trimmed) before it becomes part of a key, so `Juan@x.com` and
`juan@x.com ` count as one account.

### Limits as route dependencies

Each limit is a FastAPI dependency declared in the route's `dependencies` list: `limit_by_ip` and
`limit_by_email`. FastAPI runs that list in order, so the order of the limits is explicit in the
route. The email dependency declares the same `data` body parameter as the route, so FastAPI parses
the body once and the email is the validated `data.email`, not raw JSON. The dependency is built
from the request model (`limit_by_email(LoginRequest, ...)`), and the route's body parameter must be
named `data`.

Every request counts against the limits, successful or not: counting only failures would need the
login result to feed back into the counter. The per-IP limit is listed first: a request blocked by
IP never reaches the account's counter, so an origin that is already blocked cannot use up a
victim's attempts. A request blocked by the account's counter has already counted against the IP.
A request whose body fails validation is answered with a 422 and never reaches the email counter;
the IP counter still counts it.

Keys are built from the scope and the identifier (`ip:<address>` or `email:<address>`), and every
limit is read from `settings` when the request arrives.

### Thresholds

Configured through environment variables in `count/period` form, one variable per profile with
`_EMAIL` and `_IP` variants where both apply. Initial values, open to agreement:

| Profile | Per email | Per IP |
| --- | --- | --- |
| login | 5/minute | 20/minute |
| mail-sending (recovery and resend) | 3/hour | 10/hour |
| refresh, recovery confirm, verify confirm | — | 20/minute |
| register | — | 5/hour |

Per-IP limits are looser than per-email ones because field workers at one establishment share an IP.
The dependency reads the value from `settings` at request time, so tests can change it.

### The 429 response

- `application/problem+json` (RFC 7807), raised as a domain exception like every other backend
  error: `RateLimitedError`, `type` `/errors/rate-limited`, registered in the error catalog. The
  body carries a `retry_after` extension member, in seconds, next to the header.
- `Retry-After` carries the real reset of the window, taken from the window statistics, not a
  `period / capacity` estimate.
- `X-RateLimit-*` headers appear on 429 responses only.
- Every limited endpoint declares the 429 in its OpenAPI `responses`.

### Resilience when Redis is down

The limiter wraps two moving-window limiters, one on Redis and one on in-memory counters. Requests
go to Redis until it fails. The request that finds it down is counted in memory, not let through, and
the limiter stays in memory mode: later requests do not wait on Redis. One request at a time checks
whether Redis is back, after 1 s and then at doubling intervals up to 30 s, and the limiter returns
to Redis when the check succeeds. Outages and recoveries are logged once each
(`rate_limit.storage_unreachable`, `rate_limit.storage_recovered`).

- **Fail-open** is rejected: it removes protection from every login for the length of an outage,
  on a platform with data about minors.
- **Fail-closed** is rejected: it would make login impossible during an outage.

The backend runs as a single instance with a single process, so in-memory counting is as exact as
Redis while the outage lasts. Two costs are accepted: counters kept in memory are lost if the
backend restarts during an outage, and what was counted in memory is not carried over to Redis when
it returns. Both need an outage and a restart together, or an attacker timing an outage, which is
unlikely. If the backend is ever scaled to several instances, each counts on its own during an
outage and the effective limit becomes N times the configured one; this decision has to be
revisited then.

## Consequences

*Positives*

- Protection per account and per origin from the same service.
- Thresholds change through configuration, with no code change.
- Protection survives a Redis outage.
- One IP is not shared by every user behind the proxy.

*Negatives*

- Redis becomes an infrastructure dependency, in compose and in the deploy.
- Counters are lost across an outage and a restart together, as described above.
- The per-email limit lets an attacker temporarily block a victim's login. A short window keeps the
  damage small.
- The origin IP depends on a Railway guarantee and on a header the platform documents, not on
  anything the backend controls.
- A route with a per-email limit must name its body parameter `data`, as the dependency shares it.
- Emails are stored in Redis in plain text, as part of the counter keys, for the length of the
  window. That is deliberate: it shows which accounts are being targeted. Redis holds personal data
  and is treated accordingly.
- IPv6 addresses are counted by their /64 network, since one subscriber controls the whole /64.
  Two unrelated clients that share a /64 (some mobile carriers and hosting providers) share a
  counter.

*Neutral*

- Field workers who share an egress IP share per-IP buckets, which is why those thresholds are
  looser.

## Alternatives considered

**Reading the email with a `key_func` over `request._body`** — rejected. It gives a clean decorator,
but a change in Starlette breaks it silently and downgrades the key to IP. A logged fallback and a
two-IP test would mitigate that, not remove it.

**Keeping slowapi** — rejected. It is synchronous, so a slow or dead Redis blocks the event loop of
every request, and its fallback and route decorators depend on internals of the library. `limits`,
which slowapi wraps, has the same algorithms with an async API.

**Another async library (fastapi-limiter, PyrateLimiter, FastAPI-Cap)** — rejected. They change the
algorithm or the key model, and none offers a degraded mode, which would have to be written anyway.

**A single fixed-window counter** — rejected in favour of `moving-window`; see above.

**Two Redis databases, one per layer** — rejected. It exists to share an instance between a gateway
and a service, and there is neither here.

**Trusting `X-Forwarded-For` or `--forwarded-allow-ips`** — rejected. The first can be forged; the
second needs proxy addresses Railway does not publish.

**Generic per-IP or per-email limits** — rejected; see Dimensions and scopes.

**Account lockout and CAPTCHA** — rejected for now. Lockout lets a third party lock someone else's
account, and needs database state and an unlock flow. CAPTCHA needs changes in both apps and an
external service, and makes things worse for field workers in the field. Both are reconsidered if
rate limiting proves insufficient.


## Verification

Integration tests run against a real Redis through testcontainers:

- the 429 and its format;
- different emails keep independent counters;
- the same email from two IPs shares one bucket;
- scopes are independent of each other;
- the shared mail-sending bucket works across recovery and resend;
- with Redis down, the limit still applies, only the first request waits on a timeout, the outage
  and the recovery are logged, and counting returns to Redis.

Unit tests cover the degraded-mode transitions with a fake Redis: the check backs off, only one
request checks at a time, and the outage is logged once.

Tests lower the limits through a fixture that mutates `settings`; the rest of the suite runs with
high defaults.

The following were confirmed by the implementation and its integration tests:

- two limits stack on one endpoint in the order they are declared, including the bucket shared by
  recovery and resend;
- degraded mode covers every limit, and the limiter returns to Redis when it recovers;
- `Retry-After` reflects the real reset under the moving window.

Not yet confirmed, to be checked on the first deploy behind Railway:

- `X-Real-IP` carries the caller's address, and a forged `X-Real-IP` in the request is overwritten.
  Send 21 requests to a limited endpoint (limit 20 per minute), each with a different forged
  `X-Real-IP`: the last one must be a 429. A client on another network must not be blocked at the
  same time. If a forged header gets through, the per-IP limit can be evaded and this decision has
  to be revisited.
