# ADR-0007: Establishment request review flow — approve/reject, dedup, concurrency, and audit trail

- **Status**: Accepted
- **Date**: 2026-08-11
- **Deciders**: Backend team
- **Related**: [ADR-0006](0006-establishment-creation-requests.md), `docs/plans/admin_establishment_request_review.md`, `app/services/establishment_service.py`, `app/repositories/establishment_repository.py`, `app/models/establishment_request.py`

## Context

[ADR-0006](0006-establishment-creation-requests.md) put field-worker "this establishment is missing" notifications in their 
own `establishment_requests` table, explicitly deferring the review side: *"an admin later either 
creates the establishment or closes the request."* This ADR covers how that review actually works —
`PATCH /admin/establishment-requests/{id}/approve` and `.../reject` — and the several
sub-decisions made building it, each of which had a real alternative on the table.

Requirements driving the design:

- Approving must **create or reuse** an `Establishment` (the request has no
  `place_id`/lat/lng — the admin supplies the final, georeferenced data at review time)
  and grant the requesting field worker approved access to it, in one step.
- Two admins (or a retried request) can race to approve requests that resolve to the
  same physical place. The result must not be a raw 500, and must not silently
  double-create.
- Both outcomes notify the requester by email; rejecting must have zero side effects
  on the `establishments`/`user_establishments` tables.
- The org wants to know *who* approved/rejected each request, for later audit.

## Decision

### 1. Dedup by `place_id`, not by name/address

`approve_creation_request` looks up an existing establishment via
`EstablishmentRepository.get_by_place_id(data.place_id)` before creating one — the same
method `create_establishment` already uses for its own duplicate check. If found, that
establishment is reused instead of inserting a new row.

We built and then reverted a `find_by_name_and_address` alternative (case-insensitive
match on `name`+`formatted_address`) before landing here. `place_id` is the single
external identifier the rest of the system already trusts as "same physical location"
(it has a DB-level `uq_establishments_place_id` constraint); free-text name/address
matching would silently merge two different real-world places that happen to share a
name, and would fail to merge the same place typed with a slightly different address.

### 2. Reuse signaled via a `reused: bool` flag, not an error and not a silent overwrite

When the request resolves to an existing establishment, the admin-submitted `name`,
`formatted_address`, `city`, `province`, lat/lng are **not applied** — the existing row
is returned as-is, plus `reused: true` in the response
(`EstablishmentApprovalResponse`, a dedicated schema — not added to the generic
`EstablishmentResponse` used by unrelated establishment endpoints).

Three alternatives were rejected:

- **Raise `EstablishmentAlreadyExistsError` (409)** — the error `create_establishment`
  raises for the same underlying signal. Wrong here: approving a request for a place
  already in the catalog is the *expected success path* of create-or-reuse, not a
  failure of admin intent. A 409 would abort the whole approval — no access granted, no
  request closed — for something that isn't an error.
- **Overwrite the existing establishment with the newly submitted data** — rejected as
  unsafe: an unrelated pending request being approved could silently mutate an
  establishment that already has measurements/subjects/surveys tied to it, changed by an
  admin who never saw its current data. If two admins process two different requests for
  the same place with different data quality, "whoever approves second wins" is not a
  decision anyone actually made.
- **Differentiate via status code instead of a body field** (`201` for newly created,
  `200` for reused — the pattern `MeasurementService.register`/`upload_measurement`
  already uses for idempotent-replay-vs-new-insert). Rejected for this endpoint
  specifically:
  - The status code answers "did *this request* (the PATCH against
    `establishment-requests/{id}/approve`) succeed?" — and it always does, uniformly,
    once the request resolves. Whether the *nested* establishment was created or reused
    is a fact about a secondary resource, not about the outcome of the approve action
    itself. Overloading the primary status code with a fact about a sub-resource three
    levels removed conflates two different "success" questions into one number.
    `MeasurementService.register`'s 200/201 split is clean because there the endpoint's
    URL and resource genuinely *are* the measurement (an idempotent `PUT`-style upload) —
    that symmetry doesn't hold here.
  - A `201` is only fully correct per HTTP semantics alongside a `Location` header
    pointing at the newly created resource (`/establishments/{id}`); we don't set one,
    and adding it just to make a `201` legitimate is more machinery than the field it
    would replace.
  - This repo generates typed API clients from the OpenAPI spec
    (`docs/generate_openapi.py`) for the mobile/backoffice frontends. One status code
    and one response schema keeps that a single, simple response type; splitting the
    same logical operation across two status codes forces the generated client to model
    a discriminated-by-status response for no functional gain, and it's easy for a
    consumer that only branches on the `2xx` class to never notice the distinction
    exists at all — a named field in the body is impossible to miss once you're already
    reading the payload.

### 3. Concurrency: SAVEPOINT + `UniqueConstraintError`, not a bare `IntegrityError`

`EstablishmentRepository.create()` runs the insert inside `self.db.begin_nested()` (a
SAVEPOINT) and translates a unique-constraint violation on `place_id` into
`UniqueConstraintError("place_id", ...)` — the same pattern already used by
`measurement_repository.py`, `subject_repository.py`, and `survey_repository.py` for
their own id/uniqueness races. `approve_creation_request` catches it and re-fetches by
`place_id` to reuse the establishment the concurrent request created first (`reused` is
`True` in that branch too); `create_establishment` catches it and raises
`EstablishmentAlreadyExistsError`, matching its own synchronous-duplicate contract. Both
callers share the repo-level fix; only their *recovery* differs, per point 2's reasoning.

### 4. 404/409 checks centralized in the service, not split across repo and service

`EstablishmentRequestRepository` exposes a plain `get_by_id() -> EstablishmentRequest |
None` — no `get_by_id_or_raise`. A private service helper,
`_get_pending_request_or_raise`, does both checks approve and reject need (request
exists → `EstablishmentRequestNotFoundError`; request is still `pending` →
`EstablishmentRequestAlreadyReviewedError`) in one place, shared by both flows.

We initially added a `get_by_id_or_raise` to the repo (mirroring
`EstablishmentRepository`'s, which earns its keep with ~7 call sites across multiple
services). For establishment *requests*, both call sites needing "not found" handling
live in the same service and need the *same* additional pending-check right after — so
splitting "not found" into the repo and "already reviewed" into the service bought
nothing but an extra layer to read through. Removed once the shared helper existed.

### 5. Audit trail: `reviewed_by` FK, no new `reviewed_at` column

Migration `0e9fed34a9df` adds `reviewed_by` (UUID, nullable, `ondelete="RESTRICT"` — the
same convention as `user_id` on the same table, `responsible_id` on `Measurement`, etc.)
set from `UserActor.user_id` (the authenticated admin) on both approve and reject before
commit.

No `reviewed_at` column was added: `EstablishmentRequest.updated_at` already has
`onupdate=func.now()` and nothing else ever mutates the row after creation, so it's
already exactly "when this request was last reviewed." Both fields are exposed on
`EstablishmentCreationRequestAdminView` only — not on the field-worker-facing
`EstablishmentCreationRequestResponse` — keeping "which admin reviewed this" an
admin-internal detail.

### 6. Reject: 204, no establishment/relation side effects, email after commit

`reject_creation_request` only flips `status` to `rejected` and sets `reviewed_by` — it
never touches `establishments` or `user_establishments`. The route returns `204` with no
body (there is nothing to return: no resource was created or resolved). An optional
`reason` (`EstablishmentRequestRejection.reason`, ≤500 chars) is folded into the denial
email if the admin supplies one.

Both approve and reject send their email **after** `uow.commit()`, not inside the
transaction — matching `AdminService.approve_establishments`'s existing pattern. A failed
email should not roll back a review decision that already succeeded in the DB; `_send_email`
already fire-and-forgets by default (logs and swallows delivery failures) for
non-critical notifications like this one.

## Consequences

**Positive**

- Approve is genuinely idempotent-ish under concurrency: two admins racing to approve
  requests for the same place both succeed, both end with the requester granted access,
  and neither gets an unhandled 500.
- One shared validation path (`_get_pending_request_or_raise`) means the 404/409
  semantics for approve and reject can't drift apart.
- `reviewed_by`/`updated_at` give real audit visibility (who, when) with a one-column
  migration, no redundant timestamp.
- `create_establishment`'s existing duplicate-handling contract (`EstablishmentAlreadyExistsError`)
  stayed intact and got *safer* under concurrency as a side effect of fixing the repo
  layer for approve.

**Negative**

- `reused: true` requires the API consumer to actually read the flag; there is no
  separate warning-level signal (e.g. a distinct status code) if they don't.
- Tests that reach the approve/reject commit path need a *real*, DB-inserted admin
  (`make_user_with_role`, not the stateless `admin_headers` fixture used everywhere
  else in `tests/integration/admin/`), because `reviewed_by`'s FK constraint rejects
  the fixture's non-persisted UUID. Discovered by 9 failing tests when `reviewed_by`
  was added; fixed locally in `test_establishment_requests.py`, but the same trap
  awaits any other admin-authenticated write that starts recording actor identity.

## Alternatives considered

**`find_by_name_and_address` dedup** — built, then reverted in favor of `place_id` (point 1).

**Raise `EstablishmentAlreadyExistsError` on dedup** — rejected; would abort a successful
create-or-reuse flow as if it were a failure (point 2).

**Auto-update the reused establishment with the newer submission** — rejected as an
unsafe implicit side effect; still open as a possible future explicit action (e.g. the
admin using the existing `PATCH /establishments/{id}` update endpoint deliberately,
informed by the `reused` flag) rather than an automatic one (point 2).

**Status code (`201`/`200`) instead of a `reused` body field** — rejected; conflates the
approve action's own success (uniform, always "the request was resolved") with a fact
about a nested sub-resource, wouldn't be spec-correct without a `Location` header we
have no reason to add, and would force the OpenAPI-generated client to model two
response shapes for one logical operation instead of one (point 2).
