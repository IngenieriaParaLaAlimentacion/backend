# ADR-0019: Rate limiting on public authentication endpoints

- **Status**: Accepted
- **Date**: 2026-09-29
- **Deciders**: Backend team
- **Related**: Issue #162 (Rate Limiting en auth endpoints), Issue #174 (Acceso del backoffice: límite por IP real)

## Context

Login, refresh, password recovery, email verification and registration had no limit. That allows
password guessing by brute force, using the recovery and verification endpoints to send mail to
third parties, and saturating the service. The platform handles data about minors, which raises the
cost of a compromised account.

There is no API gateway in front of the backend, so this service is the only place a limit can be
enforced, both per origin (IP) and per account (email).

At the time of this decision the backend runs on Railway, behind its edge proxy. Behind a proxy,
`request.client.host` is the proxy's address, not the caller's: a per-IP limit keyed on it would put
every user in one bucket.

There are two kinds of caller:

- **The mobile app** connects to the backend directly, over the public network.
- **The backoffice** runs in the browser, but every call goes to the backoffice's own origin and its
  Next.js server forwards it to the backend, over either Railway's public or private network. The
  backend cannot count on seeing the user's address: what it sees is the Next.js server's, so every
  backoffice user would share one per-IP counter and one person guessing passwords could lock all of
  them out.

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

**IP.** Every request is limited. What varies is which address it is counted against, taken from
the first of these that applies. Two headers can carry it, and they differ in who writes them:

- `X-Real-IP` is written by the edge proxy, from the address the connection came from, replacing
  any value the client sent. A caller cannot choose it.
- `X-Client-IP` is written by whoever calls, and the proxy leaves it untouched. A caller can set it
  to anything, so it is believed only together with the service credential.

1. **A request forwarded by the backoffice.** The backoffice's Next.js server sets two headers on
   every call, replacing any value sent by the browser: a shared service credential in
   `X-Internal-Token` and the user's address in `X-Client-IP`. When the credential matches
   `INTERNAL_SERVICE_TOKEN` (compared in constant time), the request is counted against the address
   in `X-Client-IP`. Only the backoffice knows the credential, so only it can say whose address that
   is. Without a matching credential `X-Client-IP` is ignored, and the request is not rejected: it
   falls to step 2. Otherwise a caller could send a different address on each attempt to avoid the
   limit, or send someone else's to block them. Trust rests on the credential, not on the network,
   so the backoffice can use either the public or the private URL. If `INTERNAL_SERVICE_TOKEN` is
   not set, this step is skipped.
2. **Any other caller**, such as the mobile app, or a request that failed step 1. The request is
   counted against the address in the header named by `RATE_LIMIT_CLIENT_IP_HEADER` (default
   `X-Real-IP`), which is the address the edge proxy saw. When that header is missing or is not an
   IP address, the socket address is used. Deployments behind the proxy set
   `RATE_LIMIT_REQUIRE_X_REAL_IP=true`, so a missing header is logged as a warning. It is an
   explicit setting because the environment name cannot tell a local run from the Railway dev
   deployment: both are `development`.

If a request carries the credential but `X-Client-IP` is missing or is not an IP address, it falls
to step 2 and a warning is logged: the backoffice is misconfigured, and without the warning its
users would share one counter unnoticed.

**IPv6** addresses count by their /64 network, because one subscriber controls a whole /64 and
could otherwise rotate addresses to get around the limit. IPv4-mapped IPv6 addresses count as the
IPv4 address.

**Email** is lowercased and trimmed, so `Juan@x.com` and `juan@x.com ` are one account.

### Where the deployment must hold

Moving to another host needs no code change, only these to remain true:

- The edge proxy sets the header named by `RATE_LIMIT_CLIENT_IP_HEADER` and overwrites any value
  the client sent. Check it by sending a forged value and confirming the counter ignores it.
- The backend cannot be reached bypassing that proxy, except by the backoffice's server.
- The backoffice's server reads the user's address from the equivalent header of its own edge
  proxy, and both services hold the same `INTERNAL_SERVICE_TOKEN`. Rotating it means changing it
  on both; in between, the backoffice's requests are counted against its server's address and
  nothing is rejected.

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
- Each caller is counted against their own address, whether they come through the backoffice or
  directly from the mobile app.
- Thresholds change through configuration, with no code change.
- Protection survives a Redis outage.
- The backend's trust in the backoffice does not depend on the hosting or on the private network.

*Negatives*

- Redis becomes an infrastructure dependency, in compose and in the deploy.
- The address of direct callers depends on the edge proxy overwriting the client's header, which the
  backend does not control.
- The backoffice's users depend on the backoffice forwarding their address. If it stops, they share
  a counter and only the warning shows it.
- `INTERNAL_SERVICE_TOKEN` is one more secret to keep in both services.
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

**Trusting the private network for backoffice calls** — rejected. Correctness would depend on how
the platform routes traffic and on the backoffice keeping to that network, and it would break on a
host without one. The private network may still be used; nothing depends on it.

**Accepting the backoffice's address header without a credential** — rejected. The backend is also
reachable through its public URL, where anyone could send it and choose the counter they count
against.

**Exempting backoffice traffic from the per-IP limit** — rejected. The caller cannot be recognised
reliably on the public URL, and the backoffice login would lose its per-IP protection.
