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
| `POST` password-recovery/request | yes | yes | `mail-sending` |
| `POST` verify-email/resend | yes | yes | `mail-sending` |
| `POST` register/field-worker | — | yes | `register` |
| `POST` refresh | — | yes | `refresh` |
| `POST` password-recovery/confirm | — | yes | `password-recovery-confirm` |
| `POST` verify-email/confirm | — | yes | `verify-email-confirm` |

Recovery request and verification resend share one bucket per email (`scope="mail-sending"`, via
`shared_limit`). Both send mail to the same person, so separate buckets would let an attacker
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

The email is normalised (lowercased, trimmed) before it becomes part of a key, so `Juan@x.com` and
`juan@x.com ` count as one account.

### The email key

The per-email key is computed from `data.email`, the already validated request model, and applied
by an explicit call to `limiter.limiter.hit(...)` (or an equivalent dependency) inside the route,
alongside the per-IP decorator. It is not read from `request._body`.

`request._body` is a private Starlette attribute. If it changes, a `key_func` built on it falls back
to the IP without any error, and the per-email limit silently disappears. Reading a validated field
costs more code and has no such failure mode.

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

- `application/problem+json` (RFC 7807), built with the same `_problem_response` helper as every
  other backend error, with its own error `type`. The catalog in `docs/errors.json` is regenerated.
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
- The email limit is applied by explicit calls inside routes instead of a pure decorator, so each
  new limited endpoint has to remember to do it.

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

Before this ADR moves to Accepted, a prototype must confirm:

- two limits with different keys stack on one endpoint, and two `shared_limit` calls with distinct
  scopes work;
- degraded mode works with that stacking and with the shared bucket;
- slowapi's logs reach structlog;
- `Retry-After` reflects the real reset under `moving-window`;
- on the Railway deploy, `X-Real-IP` carries the caller's address and a forged `X-Real-IP` in the
  request is overwritten.
