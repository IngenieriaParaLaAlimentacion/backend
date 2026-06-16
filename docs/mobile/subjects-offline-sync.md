# Subjects: Offline-First Sync Contract

How the mobile app should consume `POST /api/v1/subjects` to create subjects
**offline-first**. The endpoint is an idempotent get-or-create keyed on a
client-generated UUID, so retries are always safe and cross-device duplicates are
reconciled deterministically.

A mobile engineer should be able to implement the full sync loop from this document
alone.

---

## 1. Generate the id on the device

At the moment a subject is created locally — online or offline — the device mints a
**UUID** and uses it as both the local primary key and the `id` sent to the server.

- Prefer **UUIDv7** (time-ordered → better DB index locality) when the platform
  supports it.
- **UUIDv4** is a fine universal fallback.

All locally-created child records (measurements, surveys, iron values) reference this
id **immediately**. They never wait for the server to assign one.

## 2. Local sync state machine

Track a status per locally-created subject:

```text
PENDING ──▶ SYNCING ──▶ SYNCED
                   └──▶ CONFLICT
                   └──▶ ERROR
```

Because create is idempotent on the id, a `PENDING → SYNCING` attempt can be retried
any number of times without creating duplicates.

## 3. Request

```http
POST /api/v1/subjects
Authorization: Bearer <token>
Content-Type: application/json

{
  "id": "018f6e2a-7c3a-7e21-9b6a-2b1d3c4e5f60",
  "dni": 30111222,
  "sex": "male",
  "name": "Juan",
  "last_name": "Perez",
  "birth_date": "2010-01-01",
  "is_rural": false,
  "is_indigenous": false
}
```

`id` is optional. When omitted, the server generates one (the backoffice web flow does
this). Mobile clients should **always** send it.

## 4. Response → action

| Response | Meaning | Mobile action |
|---|---|---|
| `201 Created` | New subject; server id == sent id | Mark `SYNCED`. Nothing to remap. |
| `200 OK` | Same id already existed (a prior attempt actually landed) | Mark `SYNCED`. id unchanged. |
| `409 Conflict` (`canonical_subject` in body) | This DNI already exists under a different id | Read `canonical_subject.id`; **remap** local child records from the local id to the canonical id; adopt the canonical subject; mark `SYNCED`. If local fields differ from canonical, surface for user reconciliation. |
| `422` | Invalid payload | Mark `ERROR`, surface to user; **do not** blind-retry. |
| `401` | Token expired/invalid | Refresh token, retry. |
| `5xx` / network error | Transient | Keep `PENDING`, retry with exponential backoff (safe — idempotent). |

The `409` body is an RFC 7807 `problem+json` document with a `canonical_subject`
extension member:

```json
{
  "type": "/errors/subject-already-exists",
  "title": "Subject already exists",
  "status": 409,
  "detail": "A subject with DNI 30111222 already exists.",
  "instance": "/api/v1/subjects",
  "canonical_subject": {
    "id": "018f6e2a-1111-7e21-9b6a-aaaaaaaaaaaa",
    "dni": 30111222,
    "name": "Juan",
    "last_name": "Perez",
    "sex": "male"
  }
}
```

## 5. Sync ordering

Always sync a subject **before** its child records — children FK to the subject id.
After a `409` remap, re-point children to the canonical id **before** syncing them.

## 6. Two-device dedup walkthrough

- Device 1 registers Juan offline: `id=A, dni=D`, takes measurements referencing `A`.
- Device 2 registers the same Juan offline: `id=B, dni=D`, takes a measurement
  referencing `B`.
- Device 1 syncs → `201` (subject `A`). Its measurements sync against `A`.
- Device 2 syncs the subject → `409` with `canonical_subject.id == A`. Device 2 remaps
  its local children `B → A`, adopts `A`, then syncs its measurements against `A`.
- Result: one canonical subject `A`, all measurements attached to it. No duplicates.

## 7. Idempotency guarantee & limits

- Re-POSTing the same `id` never creates a duplicate (`200`/`201` are both
  terminal-success).
- The endpoint requires a DNI; subjects without a DNI cannot use DNI-dedup (out of
  scope).
- Create never updates an existing subject. Field corrections go through
  `PATCH /api/v1/subjects/{id}`, not by re-POSTing.
