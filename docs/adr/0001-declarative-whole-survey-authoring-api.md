# ADR-0001: Declarative whole-survey authoring API

- **Status**: Accepted
- **Date**: 2026-07-06
- **Deciders**: Backoffice / backend team
- **Related**: `docs/plans/survey_authoring.md`, [ADR-0002](0002-fies-as-template-no-survey-type.md)

## Context

The `encuesta_alimentaria` module (Module 2) lets administrators and analysts author
FIES and custom surveys from the backoffice: create a survey, add/edit/delete/reorder
questions, configure per-question response types and options, and set the audience scope.

The backoffice is an **online form builder**. The user lays out the entire survey on one
screen and clicks **Save** once. Several acceptance criteria are inherently
whole-survey invariants that must be checked atomically on that save:

- CA4 / CA9 — the survey must keep **1–30 questions**.
- CA6 — question **ordering** is part of the configuration.
- CA7 / CA8 — an **edit-lock** gates structural changes once responses exist (built now
  as a forward-compatible stub; see the plan).

There is no offline-first requirement here (unlike the mobile measurement/subject upload
flows, which use client-generated UUIDs for idempotency).

## Decision

Expose survey authoring as a **declarative, whole-survey API** with server-side
reconciliation, rather than granular per-question endpoints.

- `POST /surveys` — create from a full config payload (metadata + ordered `questions[]`,
  each with its `options[]`, plus targeted `establishment` ids).
- `PUT /surveys/{id}` — submit the **entire** desired survey state. The server reconciles
  against current state by id:
  - question/option carrying a known `id` → **update**
  - question/option with no `id` → **insert**
  - known `id` absent from the payload → **delete**
- **Ordering is implicit in array position** — there is **no separate reorder endpoint**.
- Existing rows echo their **server-assigned** ids; new rows omit `id`. A supplied
  question/option id that does not belong to the target survey is **rejected**, not
  silently ignored (cross-survey ownership guard).

`is_active` is deliberately **not** part of the `PUT` body — it is owned by the create
default and a dedicated `PATCH /surveys/{id}/status` toggle, so a normal save can never
clobber the active flag.

## Consequences

**Positive**

- All whole-survey invariants (1–30 count, ordering, edit-lock) validate **atomically** in
  a single transaction on one endpoint.
- Ordering falls out of array index for free — CA6 needs no extra endpoint or `position`
  juggling API.
- The edit-lock is a **single gate** (`_assert_editable`) on the `PUT`/`DELETE` paths
  instead of being replicated across five mutation endpoints.
- Matches the backoffice "edit everything, then Save" UX exactly.

**Negative**

- Requires server-side **diff/reconciliation** logic (match questions/options by id,
  compute inserts/updates/deletes) concentrated in the service + repository.
- Larger request payloads than granular edits (the whole survey travels on every save).

## Alternatives considered

**Granular RESTful per-question endpoints** — `POST /surveys/{id}/questions`,
`PATCH /surveys/{id}/questions/{qid}`, `DELETE /surveys/{id}/questions/{qid}`, plus a
`PUT /surveys/{id}/questions/order` reorder endpoint.

Rejected: this is low-frequency authoring, not a high-throughput mutation API. The
smaller-payload / more-cacheable advantages of granular endpoints matter little here,
while atomic whole-survey validation and a single edit-lock gate matter a lot. Granular
endpoints would spread the 1–30 and lock checks across five routes and add a bespoke
reorder contract.
