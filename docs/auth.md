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

## Roles

| Role | Description                                                                |
|---|----------------------------------------------------------------------------|
| `admin` | Full access to all data and all establishments. Can manage users.          |
| `analyst` | Can view data across all establishments, including dashboards and reports. |
| `field_worker` | Can only load and view data for their assigned establishments.             |

Role is stored in the `users` table and included in the access token payload. It does not change between token refreshes without a new login.

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

Endpoints that are already caller-scoped by construction — such as `GET /api/v1/users/me/activity`,
which only ever returns rows the caller produced — need no establishment check at all.

### Linking to an establishment

Any role can hold `user_establishments` rows. How a row is created depends on the role:

| Role | Link | Unlink |
|---|---|---|
| `field_worker`, `analyst` | `POST /users/me/establishments` opens a `PENDING` request for an admin to review | `PATCH /users/me/establishments/withdraw` sets the row to `WITHDRAWN` |
| `admin`, `superadmin` | `POST /users/me/establishments/{id}/subscription` creates the row as `APPROVED`, with no review | `DELETE /users/me/establishments/{id}/subscription` deletes the row |

Admins are rejected on the request endpoint (`403`), and only admins can use the subscription endpoints.
`GET /users/me` and `GET /users/me/establishments` list the caller's rows for every role.
