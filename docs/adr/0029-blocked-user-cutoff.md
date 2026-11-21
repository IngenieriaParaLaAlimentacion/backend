# ADR-0029: Cutting off blocked users on every request

- **Status**: Accepted
- **Date**: 2026-11-19
- **Deciders**: Backend team
- **Related**: Issue #233 (Bloquear y desbloquear usuarios de la plataforma), [ADR-0019](0019-auth-rate-limiting.md)

## Context

An admin can block a user from the whole platform. A blocked user cannot log in, and a session
that is already open must stop working immediately: any later action is rejected, and the client
can tell that the reason is the block.

The access token cannot carry that decision. It is a JWT validated by signature only, valid for
15 minutes, and nothing in it changes when the user is blocked. Revoking the user's refresh
tokens stops them from getting new access tokens, but the one already issued keeps working until
it expires. Role changes accept that window (see `docs/auth.md`); a block must not.

So every authenticated request has to check, against some state outside the token, that the
user is not blocked.

Other facts that shape the decision:

- The backend is a single-instance monolith. There is no API gateway in front of it, so this
  service is the only place the check can live.
- Every authenticated route reaches its actor through one function,
  `_get_authenticated_actor`, which `require_admin`, `require_any`, `require_admin_or_analyst`
  and `get_optional_actor` all call.
- The block is stored as a user status, `blocked`, which is the source of truth. A user keeps
  their data and establishment memberships while blocked.
- Redis is already part of the deployment, for the rate limiter. The limiter degrades to
  in-memory counters when Redis is unreachable, which is correct for counters.

## Decision

### The check reads the database

`_get_authenticated_actor` reads the user's `status` from the database after validating the
token and its role, and raises `UserBlockedError` when it is `blocked`. It is a single-column
query by primary key, run in a short unit of work of its own, because the dependency runs before
the route's service opens its own.

The rule lives in one function, `check_user_not_blocked(uow, user_id)` in
`app/services/access.py`, next to the establishment access checks. The dependency opens the unit
of work and calls it, so the strategy can change without touching any route or service.

A user with no row keeps today's behaviour and is not rejected by this check.

### One error for login and for open sessions

Login and the per-request check raise the same error, `UserBlockedError`, with the error type
`user-blocked` and HTTP `403`. Clients match one error type to show the block message, whether it
arrives at login or in the middle of a session.

It is a `403` and not a `401`, so that clients do not take it for an expired token and enter a
refresh loop. At login the check runs after the password is verified, as it does for a pending
account, so a caller who does not know the password cannot find out that an account is blocked.

### Blocking also revokes refresh tokens

Blocking revokes all of the user's refresh tokens in the same transaction as the status change.
It marks tokens that were unrevoked and unexpired at that transition. Unblock clears the markers
while preserving revocation. Login, refresh, block and unblock hold the user row lock through
commit, so a token issued before the block is covered by revocation.

Mobile needs the same block notice when its access token has already expired (Mobile #110,
CA2). An opted-in refresh request gets `403 /errors/user-blocked` only for an exact, unexpired
device-bound credential marked by the current block while the account remains blocked.
Other failed refresh requests keep the generic `401`.

### What it assumes

The decision assumes a single backend instance. If the backend is ever scaled to several, the
strategy is revisited then, not now.

## Consequences

*Positives*

- An authorization check that sees the committed block rejects a protected request. A request
  that already passed the check can finish.
- One check in one function covers every authenticated route, including future ones.
- The database stays the only source of truth. There is no second copy of the block state that
  can disagree with it, and nothing to rebuild after a restart.
- No new infrastructure and no new failure mode: if the database is down the request fails anyway.

*Negatives*

- One extra query on every authenticated request, plus a second database session per request,
  because the check runs before the route's own unit of work. At the current traffic this is not
  expected to matter, but it has not been measured.
- A public endpoint that takes an optional token (`get_optional_actor`) also rejects a blocked
  caller, instead of treating them as anonymous.
- A JWT from a session that missed an entire block and unblock can work until its existing
  expiry. A client that observed the cutoff clears its session and requires fresh sign-in.

## Alternatives considered

**A Redis set of blocked user IDs, checked on each request** (the approach of a reference project
that has an API gateway) — rejected. Not being in the set does not prove the user is not blocked:
the set is wrong after Redis loses its data, after a failed write when blocking, and while Redis is
unreachable. A correct version needs a marker saying the set was rebuilt from the database, a
rebuild at startup and whenever Redis returns, a database fallback, and ordered writes. That is a
client, a store, a rebuild routine and four failure modes, to save one primary-key query on a single
instance. The in-memory fallback the rate limiter uses does not fit here, since a counter that
restarts at zero is harmless and a blacklist that restarts empty lets blocked users in.

**Redis as a cache of the user's status, with a short TTL, invalidated on block and unblock** —
deferred, not rejected. It is simpler and safer than the blacklist: losing Redis only causes misses
that go to the database, and a failed write at block time leaves a window of at most the TTL.
But the cut-off is then immediate only while every write to Redis succeeds, and Redis and
PostgreSQL are both network calls on the current host, so the saving is small. It also needs the
degraded-mode handling the rate limiter has, since the 0.2 s Redis timeouts would otherwise delay
every request during an outage. It becomes worth it if the extra database session per request
turns out to pressure the connection pool, and that should be measured first. Because of
`check_user_not_blocked`, adding it later touches that function and the dependency that calls it.

**Accepting the 15-minute window, as role changes do** — rejected. Role changes accept it, but it
would let a blocked user keep acting for up to 15 minutes, which the requirement rules out.

**Shortening the access token's lifetime** — rejected. It narrows the window without closing it,
and makes every client refresh far more often.

**A claim or version in the token compared with a stored value** — rejected. It still needs a
database read on each request, so it costs the same as reading the status and adds a field to
every token.

**Checking in each route or service** — rejected. A route that forgot the check would keep serving
a blocked user. `_get_authenticated_actor` is the one place every route already passes through.

**Returning generic `401` for every rejected refresh** — retained for legacy clients. Mobile
opts in to the typed error so it can display the same notice whether the access token was valid
or expired when the server observed the block.
