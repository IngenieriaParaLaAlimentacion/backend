# ADR-0019: Rate limiting on public authentication endpoints

- **Status**: Proposed
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

- **slowapi**, with a single `Limiter` held in `app.state.limiter`.
- **Redis** as storage, so counters survive restarts and are consistent across replicas. One
  instance and one `RATE_LIMIT_REDIS_*` configuration; nothing else in the stack uses Redis, so no
  database separation is needed. Redis is added to `compose.yml` and to the Railway deploy.
- The Redis client uses short connect and socket timeouts, so that an outage costs a request a
  bounded wait before the fallback below takes over.

### Algorithm

`strategy="moving-window"`, which avoids the double burst at the boundary of two fixed windows. It
is a constructor parameter, so reverting to fixed-window touches nothing else.

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
  `request.client.host`. In production that should not happen, so the fallback is logged as a
  warning rather than taken silently.

This trust rests on a platform guarantee. Moving off Railway means revisiting this decision.

IPv4 addresses are counted individually. IPv6 addresses are counted by their /64 network, because
a single subscriber controls a whole /64 and could otherwise rotate addresses to get around the
limit; IPv4-mapped IPv6 addresses count as the IPv4 address.

The email is normalised (lowercased, trimmed) before it becomes part of a key, so `Juan@x.com` and
`juan@x.com ` count as one account.

### The email key

The per-email limit is a second `shared_limit` decorator on the route, with its own `key_func`. That
function reads the normalised email from `request.state`, where a route dependency stored it. The
dependency declares the same `data` body parameter as the route, so FastAPI parses the body once
and the email is the validated `data.email`, not raw JSON.

Every request counts against the limits, successful or not: slowapi does not distinguish, and
counting only failures would need the login result to feed back into the counter. The per-IP limit
is checked first: a request blocked by IP never reaches the account's counter, so an origin that is
already blocked cannot use up a victim's attempts. A request blocked by the account's counter has
already counted against the IP.

Two alternatives were rejected:

- Reading `request._body` in the `key_func`. It is a private Starlette attribute; if it changes,
  the key falls back to the IP without any error and the per-email limit silently disappears.
- Calling `limiter.limiter.hit(...)` from inside the route. slowapi detects a dead storage, and
  notices its recovery, only for limits it evaluates itself. A manual `hit` would bypass that, so
  the degraded mode below would not cover the email limit.

If a route forgets the dependency, `email_key` logs an error and degrades to the IP key. It does not
raise: an exception inside a `key_func` makes slowapi treat the storage as down.

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
The decorator receives a lambda over `settings`, so the value is read at request time and can be
changed in tests.

### The 429 response

- `application/problem+json` (RFC 7807), raised as a domain exception like every other backend
  error: `RateLimitedError`, `type` `/errors/rate-limited`, registered in the error catalog. The
  body carries a `retry_after` extension member, in seconds, next to the header.
- `Retry-After` carries the real reset of the window as slowapi computes it, not a
  `period / capacity` estimate.
- `X-RateLimit-*` headers appear on 429 responses only. slowapi's `headers_enabled` adds them to
  every response, so the 429 comes from a custom handler.
- Every limited endpoint declares the 429 in its OpenAPI `responses`.

### Resilience when Redis is down

`in_memory_fallback_enabled=True`. If Redis becomes unreachable, slowapi switches to per-instance
in-memory counters and returns to Redis when it recovers. Outages and recoveries are logged; the
messages slowapi emits must reach the backend's structlog pipeline.

- **Fail-open** is rejected: it removes protection from every login for the length of an outage,
  on a platform with data about minors.
- **Fail-closed** is rejected: it would make login impossible during an outage.

The accepted cost is precision: with N replicas the effective limit becomes N times the configured
one, and in-memory counters are lost when an instance restarts.

There is a second cost, in latency. slowapi's Redis client is synchronous, so waiting on an
unresponsive Redis blocks the instance's event loop. Measured against a frozen Redis with 0.5 s
timeouts: the first request of an outage takes about 1 s (the failed hit and the failed check), the
following ones about 5 ms, and every recheck of the storage, on a delay that doubles up to 32 s,
stalls the instance for about 0.5 s. The short timeouts are what bound this.

## Consequences

*Positives*

- Protection per account and per origin from the same service.
- Thresholds change through configuration, with no code change.
- Protection survives a Redis outage.
- One IP is not shared by every user behind the proxy.

*Negatives*

- Redis becomes an infrastructure dependency, in compose and in the deploy.
- Precision drops during an outage, as described above.
- The per-email limit lets an attacker temporarily block a victim's login. A short window keeps the
  damage small.
- The origin IP depends on a Railway guarantee and on a header the platform documents, not on
  anything the backend controls.
- A route with a per-email limit needs the `remember_email` dependency next to its decorators. If it
  is forgotten the limit degrades to the IP key and an error is logged.
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
- with Redis down, requests go through the degraded mode and the error is logged.

Tests lower the limits through a fixture that mutates `settings`; the rest of the suite runs with
high defaults.

The following were confirmed by the implementation and its integration tests:

- two limits with different keys stack on one endpoint, and two `shared_limit` calls with distinct
  scopes work, including the bucket shared by recovery and resend;
- degraded mode works with that stacking and with the shared bucket, and the limiter returns to
  Redis when it recovers;
- slowapi's logs reach the backend's structlog output;
- `Retry-After` reflects the real reset under `moving-window`.

Still pending before this ADR moves to Accepted:

- on the Railway deploy, `X-Real-IP` carries the caller's address and a forged `X-Real-IP` in the
  request is overwritten.
