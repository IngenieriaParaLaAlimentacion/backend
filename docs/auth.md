# Authentication and Authorization

## Overview

Authentication is handled with custom JWT tokens. There are no external auth providers.

Authorization has two levels:
1. **Role-based**: what actions a user can perform globally.
2. **Per-establishment**: which establishments a user can access. Resolved at request time by querying the DB — not encoded in the token.

---

## Authentication

### Login flow

1. Client sends credentials via login or registration.
2. Backend verifies the password against the hashed value in `user_passwords`.
3. On success, the backend issues two tokens:
   - **Access token**: short-lived JWT, used on every request.
   - **Refresh token**: long-lived, stored hashed in `user_tokens`, bound to a `device_id`.
4. Both tokens are returned to the client.

### Access token

- Format: JWT, signed with `JWT_SECRET_USER`, `JWT_SECRET_ADMIN` or `JWT_SECRET_ANALYST`.
- Payload contains: `user_id`, `role`.
- Short-lived (TTL TBD).
- Sent by the client in the `Authorization: Bearer <token>` header.
- Stateless — not stored in the DB. Validation is signature-only.

### Refresh token

- Long-lived (7 days).
- Stored **hashed** in the `user_tokens` table — the raw token is never persisted.
- Bound to a `device_id` so sessions can be managed per device.
- Can be revoked individually (sets `revoked = true`).
- The `role` is snapshotted at issue time and stored in `user_tokens` for audit purposes.

### Token refresh flow

1. Client sends the refresh token.
2. Backend hashes it and looks it up in `user_tokens` (by `token_hash + device_id + revoked = false`).
3. If valid and not expired, issues a new access token.

---

## Rate limiting

The public authentication endpoints are rate limited per origin (IP) and, where the request
carries an email, per account. Every request counts against a limit, successful or not. Decision
and alternatives: [ADR-0019](adr/0019-auth-rate-limiting.md).

| Endpoint | Per email | Per IP |
|---|---|---|
| `POST /auth/login` | `RATE_LIMIT_LOGIN_EMAIL` | `RATE_LIMIT_LOGIN_IP` |
| `POST /auth/password-recovery/request` | `RATE_LIMIT_MAIL_SENDING_EMAIL` (shared) | `RATE_LIMIT_MAIL_SENDING_IP` |
| `POST /auth/verify-email/resend` | `RATE_LIMIT_MAIL_SENDING_EMAIL` (shared) | `RATE_LIMIT_MAIL_SENDING_IP` |
| `POST /auth/register/field-worker` | — | `RATE_LIMIT_REGISTER_IP` |
| `POST /auth/refresh` | — | `RATE_LIMIT_TOKEN_IP` |
| `POST /auth/password-recovery/confirm` | — | `RATE_LIMIT_TOKEN_IP` |
| `POST /auth/verify-email/confirm` | — | `RATE_LIMIT_TOKEN_IP` |

- Each endpoint has its own counters. The only shared one is the per-email counter of password
  recovery and email verification resend, since both send mail to the same person.
- Limits are written `<count>/<period>` (`5/minute`, `3/hour`) and read from `settings` on every
  request. A value that is not written that way stops the backend at startup. Defaults are in
  `app/config/settings.py` and `.env.example`.
- The email is lowercased and trimmed before counting. IPv4 addresses count individually and IPv6
  addresses by their /64 network.
- The address a request is counted against comes from the first of these that applies:
  1. A request forwarded by the backoffice that carries `X-Internal-Token` equal to
     `INTERNAL_SERVICE_TOKEN` is counted against the user address in `X-Client-IP`. Without a
     matching token the header is ignored, so a public caller cannot choose its counter. If the
     token matches but the address is missing or is not an IP address, a warning is logged and the
     request goes to the next rule. With `INTERNAL_SERVICE_TOKEN` unset this rule is skipped.
  2. Any other request is counted against the header named by `RATE_LIMIT_CLIENT_IP_HEADER`
     (`X-Real-IP`, set by the Railway edge proxy). When it is missing or is not an IP address, the
     socket address is used and a warning is logged.
- Requests that fail validation still count against the per-IP limit but never reach the per-email
  one. `POST /auth/verify-email/resend` counts per email whether or not the account exists, so the
  limit does not reveal which emails are registered.
- Going over a limit returns `429` with `Retry-After`; see [Rate limit responses](api.md#rate-limit-responses).

### Counter storage

Counters live in Redis (`RATE_LIMIT_REDIS_URL`), so they survive restarts and agree across
instances. Locally, `docker compose up redis` starts one. On Railway, add a Redis service and set
`RATE_LIMIT_REDIS_URL` on the backend to its connection URL.

If Redis becomes unreachable the backend keeps limiting with in-memory counters and logs
`rate_limit.storage_unreachable`. It checks for Redis again after 1 s, then at doubling intervals up
to 30 s, and returns to it on its own, logging `rate_limit.storage_recovered`. The memory counters
are exact while the backend is a single instance; with several instances the effective limit would
be multiplied by their number. What was counted in memory is not carried over to Redis when it
returns, and it is lost if the backend restarts during the outage.

The Redis connections are closed when the backend shuts down.

### Adding a limited endpoint

Add the limits to the route's `dependencies`, per-IP first so it is checked first:
`limit_by_ip("<setting>", scope="<scope>")` and, for an endpoint that carries an email,
`limit_by_email(<RequestModel>, "<setting>", scope="<scope>")`. The route's body parameter must be
named `data`. Declare `**RATE_LIMITED_RESPONSES` (from `app/api/v1/params.py`) in `responses`. See
`app/api/v1/auth.py`.

---

## Roles

| Role | Description                                                                |
|---|----------------------------------------------------------------------------|
| `superadmin` | Same as `admin`, and can also change the role of admins. Never assignable through the API. |
| `admin` | Full access to all data and all establishments. Can manage users.          |
| `analyst` | Can view data across all establishments, including dashboards and reports. |
| `field_worker` | Can only load and view data for their assigned establishments.             |

Role is stored in the `users` table and included in the access token payload. A token
refresh reissues the access token with the role snapshotted in `user_tokens`, so a role
only changes for a session through a new login.

### Changing a user's role

`PATCH /api/v1/admin/users/{user_id}/role` (contract in `docs/api.md`). The rule lives in
`AdminService` (`_ROLE_CHANGE_SOURCES`):

| Actor | May change users with role | To |
|---|---|---|
| `admin` | `field_worker`, `analyst` | `field_worker`, `analyst`, `admin` |
| `superadmin` | `field_worker`, `analyst`, `admin` | `field_worker`, `analyst`, `admin` |

- Nobody may change a `superadmin` or their own role.
- Only `active` users can change role: a pending invitation's link depends on the role.
- The change revokes all of the user's refresh tokens in the same transaction, forcing a
  new login. The access token already issued keeps the old role until it expires
  (≤ 15 min); this window is accepted.

---

## Per-establishment authorization

Establishment access is **not encoded in the JWT**. It is resolved at the endpoint level on every request by querying the `user_establishments` table.

This means:
- Permissions can be updated without invalidating active sessions.
- One shared service helper, `app/services/access.py::check_establishment_access`, owns the check — **never re-implement the rule inline**.

### How it works

There is **no middleware**. A service that touches establishment-scoped data calls
`check_establishment_access(uow, actor, establishment_id)` explicitly:

1. The route's auth dependency validates the JWT and builds a `UserActor` from `user_id` and `role`.
2. The service passes that actor and the establishment id to `check_establishment_access`.
3. `admin` and `analyst` return immediately — only `field_worker` is establishment-scoped.
4. For a field worker, the helper queries `user_establishments` and requires an `APPROVED` relation.
5. Otherwise it raises `EstablishmentAccessDeniedError`, which surfaces as `403 Forbidden`.

Field work that only field workers get by role — today, submitting and editing survey
responses — also lets in an analyst who is linked like a field worker. It goes through
`check_field_work_access(uow, actor, establishment_id)` in the same module:

1. Every role except `analyst` returns immediately.
2. An analyst needs an `APPROVED` relation to `establishment_id`, or to any establishment
   when the work names none (subject or anonymous surveys).
3. Otherwise it raises `EstablishmentAccessDeniedError` (`403`).

Endpoints that are already caller-scoped by construction — such as `GET /api/v1/users/me/activity`,
which only ever returns rows the caller produced — need no establishment check at all.

### Linking to an establishment

Any role can hold `user_establishments` rows. How a row is created depends on the role:

| Role | Link | Unlink |
|---|---|---|
| `field_worker`, `analyst` | `POST /users/me/establishments` opens a `PENDING` request for an admin to review | `PATCH /users/me/establishments/withdraw` sets the row to `WITHDRAWN` |
| `admin`, `superadmin` | `POST /users/me/establishments/subscriptions` creates the rows as `APPROVED`, with no review | `DELETE /users/me/establishments/subscriptions?establishment_ids=...` deletes the rows |

Admins are rejected on the request and withdraw endpoints (`403`), and only admins can use the subscription endpoints.
`GET /users/me` and `GET /users/me/establishments` list the caller's rows for every role.
