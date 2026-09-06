# Spec: Manual response number on survey responses

- **Status**: Ready for implementation
- **Date**: 2026-09-06
- **Module**: `encuesta_alimentaria` (Module 2)
- **ADR**: [ADR-0012](../adr/0012-manual-response-number-on-survey-responses.md)
- **Amends the contract established by**: [ADR-0004](../adr/0004-offline-first-response-sync-via-client-ids.md), [ADR-0008](../adr/0008-survey-response-target.md)

## Problem Statement

Analysts distribute fieldwork by handing out **number ranges**. Three field workers go
out with the same survey; one is told to use 1 through 50, the next 51 through 100, the
next 101 through 150. Every paper form and every interview carries the number the field
worker wrote on it, and that number is how the analyst later recognises whose batch a
record belongs to, notices that number 74 never arrived, and reconciles the digital
record against the folder the worker carried.

The platform has no representation of this number. A survey response is identified by a
UUID primary key — right for offline sync, meaningless to a person holding a clipboard —
and, when the survey's response target is `anonymous`, by nothing else at all. Analysts
cannot search by the number they assigned, cannot ask for "everything in 51–100", and
cannot spot a missing record. Field workers cannot find an interview in their history by
the number they wrote on the form. The reconciliation happens off-platform or not at all.

Modelling the number as an extra survey question would put it inside the response's
answers blob, where it cannot be rendered in a list view without loading the survey
definition, cannot be filtered by range, and cannot be constrained to be unique — which
is why it was rejected by the product owner before this spec was written.

## Solution

Every survey response carries a **response number**: a positive integer the field worker
types in by hand at submission time, required on every survey regardless of response
target, and unique within its survey.

A field worker enters the number from their paper form alongside the answers. If that
number is already taken in that survey, the submission is rejected with a conflict that
names the response already holding it, and the worker corrects the number and resubmits;
their record is never silently accepted under a different number. The number can be
corrected afterwards by the submitter or an admin, exactly the way an answer can.

Analysts see the number in the survey's response list and detail view, filter the list to
an exact number or to a range, and carry both the number and the filter through to the
XLSX exports. Field workers see it on every row of their response history in the
mobile app. Range assignment itself stays where it already lives — in the analyst's head
and in the conversation with the field worker; the platform records and enforces the
number, it does not administer the ranges.

## User Stories

### Submitting

1. As a field worker, I want to enter the response number from my paper form when I
   submit a survey response, so that the digital record can be matched to the form in my
   folder.
2. As a field worker, I want the response number to be required on every survey I answer
   — including anonymous ones — so that no response I take ends up without a
   human-readable identifier.
3. As a field worker, I want a number outside the accepted range to be rejected
   immediately, so that a date typed into the wrong field never becomes a permanent
   identifier.
4. As a field worker working offline, I want my response and its number stored on the
   device and synced when connectivity returns, so that fieldwork in areas without signal
   loses nothing.
5. As a field worker, I want a retried sync of a response I already submitted to be
   recognised as the same response, so that my own record is never reported as a conflict
   against itself.
6. As a field worker, I want a duplicate number to be rejected with an error that names
   the response already holding that number, so that I understand what happened rather
   than seeing a generic failure.
7. As a field worker whose submission was rejected for a duplicate number, I want the
   record to remain on my device, so that I can change the number and resubmit without
   redoing the interview.
8. As a field worker, I want to be told about a duplicate target before a duplicate
   number when both apply, so that I do not renumber a response that will be rejected
   anyway.
9. As a field worker, I want a number I choose that nobody else used to be accepted even
   if it falls outside the range I was verbally assigned, so that a mistake in the range
   hand-off does not block the fieldwork.

### Editing

10. As a field worker, I want to correct a mistyped response number on a response I
    submitted, so that a one-digit error does not require escalating to an admin.
11. As an admin, I want to correct the response number on any response, so that data can
    be fixed when the original submitter is unreachable.
12. As an admin, I want an edit that moves a response onto a number already taken to be
    rejected, so that uniqueness holds after edits and not only at submission.
13. As an admin, I want re-submitting an edit that does not change the number to succeed,
    so that editing only the answers is never blocked by the response's own number.
14. As an admin, I want every edit audit entry to record the response number as well as
    the answers, so that the audit trail shows the complete state of the response after
    each edit.
15. As an admin, I want two edits made offline on different devices to be resolved by
    when they were made rather than when they arrived, so that a late-syncing older edit
    does not overwrite a newer one — for the number as well as the answers.
16. As an analyst, I want a retried edit sync to be recognised as already applied, so
    that a retry does not append a duplicate audit entry.

### Reading — dashboard

17. As an analyst, I want the response number shown on every row of a survey's response
    list, so that I can identify records without opening each one.
18. As an analyst, I want the response number in the response detail view, so that I can
    confirm I am looking at the record I was asked about by number.
19. As an analyst, I want to filter a survey's responses to an exact response number, so
    that I can jump straight to the record a field worker referred to by number.
20. As an analyst, I want to filter a survey's responses to a number range, so that I can
    see everything produced by the field worker I gave that range to.
21. As an analyst, I want an inverted range to be rejected with a clear error, so that a
    typo in the bounds does not silently return nothing.
22. As an analyst, I want a range that matches nothing to return an empty page rather than
    an error, so that "nothing has synced yet" reads as a normal result.
23. As an analyst, I want the number displayed next to the submitter's name, so that I can
    see at a glance whether a worker stayed inside the range I assigned them.
24. As an analyst, I want gaps within a filtered range to be visible, so that I can tell a
    response never arrived and chase the field worker for it.

### Exporting

25. As an analyst, I want the response number as a leading column in the XLSX export, so
    that the workbook can be reconciled row by row against the paper forms.
26. CSV export is out of scope; XLSX is the supported survey-response export format.
27. As an analyst, I want the export to honour the number filters, so that exporting after
    narrowing to a range gives me that range rather than the entire survey.

### Reading — mobile

28. As a field worker, I want the response number on each row of my response history, so
    that I can find a specific interview by the number I wrote on the form.
29. As a field worker, I want the number returned by the paginated history endpoint
    itself, so that the list renders without an extra request per row.

### Operating

30. As an analyst, I want numbers to be unique per survey rather than globally, so that
    assigning 1–50 in one survey does not consume those numbers in another.
31. As an analyst, I want to keep assigning ranges verbally, so that I am not forced to
    configure ranges in the backoffice before sending anyone into the field.
32. As an admin, I want existing responses to receive numbers automatically when the
    feature ships, so that the new required field does not break reading historical
    records.
33. As a developer, I want the backfill and the uniqueness constraint applied together, so
    that there is no deployment window in which the invariant is unenforced.

## Implementation Decisions

### Schema

- **`survey_responses` gains `response_number`**: a `NOT NULL` integer. It is not a
  foreign key, does not participate in the existing "at most one target" check
  constraint, and is required identically for the `subject`, `establishment` and
  `anonymous` response targets.
- **A unique index on `(survey_id, response_number)`.** Not partial — the column is
  non-nullable. This is the third unique constraint on this table, alongside the primary
  key and the two partial per-target indexes from ADR-0008.
- **`survey_response_edits` gains its own `NOT NULL response_number`**, so an audit
  snapshot records the response's full post-edit state rather than only its answers.
  This mirrors how that table already stores a complete `answers` snapshot rather than a
  diff.
- **One Alembic revision** performs: add nullable column → backfill responses with
  `row_number() over (partition by survey_id order by created_at, id)` → backfill each
  edit row from its parent response → `SET NOT NULL` on both → create the unique index.
  Single revision because the backfill without the constraint and the constraint without
  the backfill are each meaningless. `downgrade` drops the index and both columns.
- The backfill is safe because every environment holding survey responses today is a
  test environment; the assigned numbers correspond to no paper form and exist only to
  satisfy the constraint.

### Validation

- The number is validated at the **schema layer** to `1`–`999999` inclusive, producing a
  `422` outside those bounds. The upper bound exists to catch a date typed into the wrong
  field, not for arithmetic reasons.
- Requiredness is structural: the field is mandatory in both the submit and the edit
  request bodies. There is no per-survey opt-in flag and no optional phase.

### Submit path

Ordering inside the survey response service, extending the sequence ADR-0008 established:

1. Idempotent replay by client-supplied id — an already-known id returns the stored
   response unchanged, before any conflict rule is evaluated.
2. Survey lookup, target resolution, target entity lookups.
3. Target conflict check (one response per subject/establishment per survey).
4. **Duplicate response number check.**
5. Answer validation, then FIES scoring.

When a submission is both a target conflict and a number conflict, **the target conflict
is reported** — it is the unrecoverable one, and sending the field worker to renumber a
response that will be rejected regardless is a dead end.

### Conflict contract

- A duplicate number returns **`409` reusing the existing `survey-response-already-exists`
  error type**, rather than introducing a new one. Its detail message is parameterized so
  the two conflicts it now represents read differently; the RFC 7807 `type` URI is shared.
- The `existing_response` extension — already carrying the conflicting response's id,
  submitter and event timestamp — additionally carries its `response_number`.
- **The lost-read-race path must be covered.** The response repository already reads the
  violated constraint's name off the driver error and maps it to the field that collided;
  it gains a `response_number` case, and the service gains the matching branch that
  re-reads the conflicting row and raises the same `409`. Omitting this reproduces the
  exact `500`-instead-of-`409` bug documented at length in ADR-0008, because under
  asyncpg the constraint name lives at `error.orig.__cause__` rather than on `diag`.

### Edit path

- `response_number` is **required** in the edit request body and replaced under the same
  full-replace semantics as the answers. Making it optional-to-mean-unchanged was
  rejected: it would give one request body two different update models.
- Permitted to the same actors as any response edit — the original submitter, or an
  admin/superadmin.
- The uniqueness check re-runs on edit and is **skipped when the value is unchanged**, so
  editing only the answers is never blocked by the response's own number.
- Every edit attempt appends an audit row carrying the submitted number, whether or not
  the edit wins the last-write-wins comparison; the response's current state advances only
  when the incoming `event_at` is at least as recent, exactly as today.
- Per-edit-attempt idempotency by client-supplied edit id is unchanged.

### Read surface

- **Returned in**: the standard survey response payload, the dashboard detail payload, the
  dashboard listing item, and the activity-feed item that backs the mobile response
  history. Every paginated endpoint that returns a response returns its number.
- **Filterable** on the survey response listing by exact value and by range, via three
  query parameters: an exact match and a `from`/`to` pair. Inverted bounds are rejected
  with the same validation error shape the existing date-range filters use.
- **The export accepts the same filters**, alongside the target filters it already honours.
  An export taken after narrowing to a range returns that range.
- **Not sortable.** No new members are added to the response sort order; the range filter
  covers the workflow.
- **Not on the cross-survey analytics summary**, where a per-survey number has no meaning.
- **Written as a leading column** in the XLSX export, before the existing
  identity and metadata columns.

### Documentation

- ADR-0012 records the decision and its rejected alternatives.
- The generated error catalog and OpenAPI document are regenerated; the error catalog gains
  no new entry, since the existing conflict type is reused.
- No new mobile-facing document; the response history contract change is a single added
  field.

## Testing Decisions

### What a good test looks like here

A good test in this codebase asserts **external behaviour through a stable seam** — the
HTTP status and body a client receives, or the value a service returns to its caller —
and never the internal ordering of calls that produced it. Tests that assert "the
repository was called with these arguments" break on refactors that change nothing a
client can observe, and are avoided. Fixtures build real rows through the same public
API a client would use wherever practical.

### Seams

The intent is to add **no new seams**. Every behaviour in this spec is reachable through
seams that already exist:

- **Primary seam — the HTTP API, integration-tested against real Postgres.** The existing
  survey-response integration suite drives a real FastAPI app over a Testcontainers
  Postgres with Alembic migrations applied to head. This is the highest seam available and
  it exercises the whole stack in one pass: schema-level bounds validation, the service's
  check ordering, the unique index itself, the `409` body, the filters' SQL, and the
  migration's DDL (every integration test runs against a schema produced by the real
  migration). Almost everything in this spec should be tested here and nowhere else.
- **Secondary seam — the survey response service with a mocked unit of work.** The
  existing service unit suite is the right place for exactly one thing the HTTP seam
  cannot force deterministically: the **lost-read-race branch**, where the pre-check
  passes and the database raises the unique violation. ADR-0008 established the precedent
  — its equivalent race is covered by an integration test that blinds the service's
  pre-check so the index path is exercised against real Postgres, plus mock-level tests for
  the branch logic. The same two-pronged approach applies to the number's race branch.
- **Exporter seam — the XLSX exporter, unit-tested as a pure function.** It has a unit suite
  that feeds domain objects in and asserts on the produced bytes.
  The new leading column is asserted there; the export endpoint's handling of the new
  filters is asserted at the HTTP seam.

No new seam is proposed. If one proves necessary during implementation, it should be
raised rather than added silently.

### Coverage to add

At the HTTP seam:

- Submission with a valid number succeeds and returns it.
- Submission without a number, with zero, with a negative number, with a non-integer, and
  above the upper bound each fail validation.
- A number is required for all three response targets, including anonymous and FIES.
- A duplicate number within one survey returns `409` with the conflicting response — its
  id, submitter and number — in `existing_response`.
- The same number in a *different* survey is accepted.
- A retried sync of an existing response id returns the stored response rather than a
  duplicate-number conflict.
- When both a duplicate target and a duplicate number apply, the target conflict is the
  one reported.
- An edit changing the number succeeds; an edit onto a taken number is rejected; an edit
  leaving the number unchanged succeeds.
- An edit that loses the last-write-wins comparison still appends an audit row carrying its
  number without advancing the response.
- The number appears in the standard payload, the detail payload, the dashboard listing and
  the activity feed.
- Exact-match, range, inverted-range and empty-result filtering on the listing.
- The export honours the number filters and carries the leading column.
- Role and ownership rules are unchanged — the number introduces no new authorization.

At the service seam: the race branch, and the precedence of target conflict over number
conflict at the level of raised exceptions.

At the exporter seams: the leading column in both formats, for subject-targeted and
non-subject-targeted surveys.

## Out of Scope

- **Range assignment.** No model of assigned ranges, no per-worker range configuration in
  the backoffice, no server-side validation that a submitted number falls inside a range
  the field worker holds, and no warning when it does not. If this is ever brought
  in-system, the natural shape is a per-survey, per-user range record validated on the
  submit path; the column added here is what it would validate against, so nothing in this
  spec blocks it.
- **Gap detection as a feature.** Analysts spot missing numbers by reading a filtered list.
  No endpoint reports "numbers 12, 40 and 74 are missing from this range".
- **Sorting by response number.** Explicitly declined.
- **The cross-survey analytics summary.** Unchanged.
- **Other modules.** `talla_y_peso` measurements and the future `valores_de_hierro`
  records get no equivalent field. The concept transplants cleanly and is deliberately not
  generalised on a single example.
- **A dedicated error type for duplicate numbers.** Declined in favour of reusing the
  existing conflict type.
- **A transition period for clients.** The field is required from the first deploy; there
  is no optional phase and no per-survey opt-in.
- **Reinterpreting the backfilled numbers.** They are arbitrary and are not intended to
  match anything.

## Further Notes

- **A duplicate surfaces late, by design.** Under offline-first sync a field worker can
  finish an interview and only learn at sync — possibly days later — that their number was
  taken. This is the same failure shape ADR-0008 already accepted for duplicate targets, on
  the same endpoint, so the mobile client's existing late-`409` handling applies. The
  important difference to communicate to the client team: a target conflict is terminal for
  the second submitter, whereas a number conflict is **recoverable** — change the number,
  resubmit.
- **Reusing the error type has a client-side cost.** Two conflicts now share one `type`
  URI, so distinguishing them means reading the detail text or inferring from the request.
  This was a deliberate product decision. If clients begin string-matching the detail,
  splitting into a dedicated type is a backward-compatible addition made later.
- **This is a breaking change for any client already submitting responses.** A build that
  does not send the field receives a `422`. Acceptable only while the service is
  pre-production — the same condition ADR-0008 relied on when it deleted every historical
  response.
- **The backfill's data path is not covered by the test suite.** Integration tests run
  migrations against an empty database, so the DDL is exercised on every run but the
  `row_number()` backfill has no rows to act on. Verify it manually against a copy of the
  test environment's data before merging.
- **The remaining deliverable before code** is the implementation plan under `docs/plans/`,
  which this spec and ADR-0012 are the inputs to.
