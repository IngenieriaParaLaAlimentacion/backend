# ADR-0007: Establishment request review flow — approve/reject, dedup, concurrency, and audit trail

- **Status**: Accepted
- **Date**: 2026-08-11
- **Deciders**: Backend team
- **Related**: [ADR-0006](0006-establishment-creation-requests.md), `app/services/establishment_service.py`, `app/repositories/establishment_repository.py`, `app/repositories/establishment_request_repository.py`, `app/models/establishment_request.py`, `AdminService.approve_establishments`/`reject_establishments`

## Context

[ADR-0006](0006-establishment-creation-requests.md) put field-worker "this establishment is missing" notifications in their 
own `establishment_requests` table, explicitly deferring the review side: *"an admin later either 
creates the establishment or closes the request."* This ADR covers how that review actually works —
`PATCH /admin/establishment-requests/{id}/approve` and `.../reject` — and the several
sub-decisions made building it, each of which had a real alternative on the table.

Requirements driving the design:

- Approving must **create or reuse** an `Establishment` (the request has no
  `place_id`/lat/lng — the admin supplies the final, georeferenced data at review time).
  The requesting field worker's access to it is left **pending**, for an admin to approve
  through the review flow that already exists for that
  (`AdminService.approve_establishments`/`reject_establishments`, exposed at
  `PATCH /admin/field-worker/{user_id}/establishments/approve|reject`).
- Two admins (or a retried request) can race to approve requests that resolve to the
  same physical place. The result must not be a raw 500, and must not silently
  double-create. Two admins can also race to review the *same* request; only one may win.
- Both outcomes notify the requester by email; rejecting must have zero side effects
  on the `establishments`/`user_establishments` tables.
- Admins need to know *who* approved/rejected each request, for later audit.

## Decision

### 1. Dedup by `place_id` only, reuse signaled via a `reused: bool` flag

`approve_creation_request` looks up an existing establishment via
`EstablishmentRepository.get_by_place_id(data.place_id)` before creating one — the same
method `create_establishment` already uses for its own duplicate check. `place_id` is
the single field checked, and the only one that could be: it's the external identifier
the rest of the system already trusts as "same physical location," backed by a DB-level
`uq_establishments_place_id` constraint. Matching on free-text `name`/`formatted_address`
instead would silently merge two different real-world places that happen to share a
name, and fail to merge the same place typed with a slightly different address — it's
not a reliable enough signal to dedup on, `place_id` is.

When a match is found, that establishment is **reused** instead of inserting a new row:
the admin-submitted `name`, `formatted_address`, `city`, `province`, lat/lng are **not
applied** to it — the existing row is returned as-is, plus `reused: true` in the response
(`EstablishmentApprovalResponse`, a dedicated schema — not added to the generic
`EstablishmentResponse` used by unrelated establishment endpoints). Callers care about
`reused` for two reasons that both come back later in this ADR: it decides how access is
granted to the requester (point 2) and it's the signal a concurrent approval recovers
with when it loses a creation race (point 3).

Three alternatives for representing that reuse were rejected:

- **Raise `EstablishmentAlreadyExistsError` (409)** — the error `create_establishment`
  raises for the same underlying signal. Wrong here: approving a request for a place
  already in the catalog is the *expected success path* of create-or-reuse, not a
  failure of admin intent. A 409 would abort the whole approval — no access left pending,
  no request closed — for something that isn't an error.
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

### 2. Access-granting decoupled from request approval

`approve_creation_request` originally granted the requesting field worker **approved**
access to the establishment in the same step as approving the request
(`create_or_approve_relation`). It now only creates/reuses the establishment and leaves
a **pending** `UserEstablishment` relation via the private helper
`_leave_access_pending`, for an admin to approve separately through the flow that
already exists for that — the same one used when a field worker registers and requests
access to an establishment that already exists.

`_leave_access_pending` branches on whether the establishment was reused:

- **Newly created** (`reused=False`): no prior relation can exist yet, so a pending one
  is staged directly (`preset_relation`), no lookup needed.
- **Reused** (`reused=True`): two field workers can independently request the same
  physical place under different wording, so a relation may already exist from a prior,
  unrelated review. It's looked up first (`get_relation`): approved or already-pending
  relations are left as-is (approving *this* request must not silently downgrade or
  reset access already granted through a different one), a rejected relation is reopened
  to pending, and only a genuinely missing relation is staged fresh.

The approval email changed accordingly: `send_access_granted_email` (still used by
`AdminService.approve_establishments` for the actual access-grant step) is replaced on
this endpoint by `send_establishment_created_email`, which tells the field worker the
establishment was created and that access is pending admin review — it does not claim
access was granted.

**Rejected alternative**: keep granting access in the same step. This conflates two
orthogonal concerns — *does the establishment exist* and *should this worker access
it* — into one action, and doesn't hold up under reuse: an establishment resolved from
one field worker's request may have nothing to do with another field worker's fitness to
access it, and the existing admin-review flow for establishment access already exists
specifically to make that a deliberate, separate decision.

### 3. Concurrency on establishment creation: SAVEPOINT + `UniqueConstraintError`, not a bare `IntegrityError`

`EstablishmentRepository.create()` runs the insert inside `self.db.begin_nested()` (a
SAVEPOINT) and translates a unique-constraint violation on `place_id` into
`UniqueConstraintError("place_id", ...)` — the same pattern already used by
`measurement_repository.py`, `subject_repository.py`, and `survey_repository.py` for
their own id/uniqueness races. `approve_creation_request` catches it and re-fetches by
`place_id` to reuse the establishment the concurrent request created first (`reused` is
`True` in that branch too); `create_establishment` catches it and raises
`EstablishmentAlreadyExistsError`, matching its own synchronous-duplicate contract. Both
callers share the repo-level fix; only their *recovery* differs, per point 1's reasoning.

### 4. Concurrency on request review: atomic `UPDATE ... WHERE status = pending ... RETURNING`, not a service-level check-then-act

Two admins reviewing the *same* request at once is a separate race from point 3's — a
TOCTOU on the request's own `pending` status, not on `place_id`. The original design
(a private service helper doing `get_by_id` then checking `status == pending` in
Python) had a window between the check and the write where a second reviewer could pass
the same check before the first one committed, producing two establishments (or an
establishment plus a stray pending-access row) for one request.

`EstablishmentRequestRepository.mark_reviewed_or_raise(request_id, status, reviewer_id)`
closes it with a single atomic statement — `UPDATE ... WHERE id = :id AND status =
'pending' ... RETURNING` — run as the **first step** of both `approve_creation_request`
and `reject_creation_request`, before any other side effect. The `WHERE status =
pending` clause is what makes it atomic: only one of two concurrent reviews can match
and return a row. The loser gets `EstablishmentRequestAlreadyReviewedError` immediately,
with no establishment created and no access relation touched — `get_by_id` is used only
afterward, to distinguish "already reviewed" (409) from "never existed" (404) for the
loser/caller. This puts the check in the repo rather than the service specifically
because atomicity requires the check and the write to be the same statement — a
service-layer check-then-act can't do that no matter how it's organized.

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

- Approve is genuinely idempotent-ish under concurrency, on both axes: two admins racing
  to approve requests for the same *place* both succeed and both resolve to the same
  establishment (point 3); two admins racing to review the same *request* — approve,
  reject, or one of each — have exactly one winner and one clean 409, with no partial
  establishment/access side effects from the loser (point 4).
- Resolving the establishment and granting the field worker access to it are now
  separate decisions, made through their own dedicated flows — approving a creation
  request can't accidentally grant or reset access tied to an unrelated prior review of
  the same establishment.
- `reviewed_by`/`updated_at` give real audit visibility (who, when) with a one-column
  migration, no redundant timestamp.
- `create_establishment`'s existing duplicate-handling contract (`EstablishmentAlreadyExistsError`)
  stayed intact and got *safer* under concurrency as a side effect of fixing the repo
  layer for approve.

**Negative**

- `reused: true` requires the API consumer to actually read the flag; there is no
  separate warning-level signal (e.g. a distinct status code) if they don't.
- Approving a creation request no longer gets the field worker into the establishment in
  one action — it now takes a second, separate admin action
  (`PATCH /admin/field-worker/{user_id}/establishments/approve`) before they have access,
  even though the establishment already exists after the first step.
- Tests that reach the approve/reject commit path need a *real*, DB-inserted admin
  (`make_user_with_role`, not the stateless `admin_headers` fixture used everywhere
  else in `tests/integration/admin/`), because `reviewed_by`'s FK constraint rejects
  the fixture's non-persisted UUID. Discovered by 9 failing tests when `reviewed_by`
  was added; fixed locally in `test_establishment_requests.py`, but the same trap
  awaits any other admin-authenticated write that starts recording actor identity.

## Alternatives considered

**Raise `EstablishmentAlreadyExistsError` on dedup** — rejected; would abort a successful
create-or-reuse flow as if it were a failure (point 1).

**Auto-update the reused establishment with the newer submission** — rejected as an
unsafe implicit side effect; still open as a possible future explicit action (e.g. the
admin using the existing `PATCH /establishments/{id}` update endpoint deliberately,
informed by the `reused` flag) rather than an automatic one (point 1).

**Status code (`201`/`200`) instead of a `reused` body field** — rejected; conflates the
approve action's own success (uniform, always "the request was resolved") with a fact
about a nested sub-resource, wouldn't be spec-correct without a `Location` header we
have no reason to add, and would force the OpenAPI-generated client to model two
response shapes for one logical operation instead of one (point 1).

**Grant access in the same step as approval (original behavior)** — reverted; conflated
resolving the establishment with deciding this specific worker should access it, and
skipped the existing dedicated review flow for establishment access (point 2).

**Service-level check-then-act for request review** (`_get_pending_request_or_raise`,
doing `get_by_id` then checking `status == pending` in Python) — reverted for approve
and reject alike, after this exact pattern turned out to have a TOCTOU race between two
concurrent reviewers; replaced by the atomic `mark_reviewed_or_raise` (point 4).
