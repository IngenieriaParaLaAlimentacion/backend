# ADR-0012: A manually entered, per-survey response number on survey responses

- **Status**: Accepted
- **Date**: 2026-09-06
- **Deciders**: Backend team (design interview with product owner)
- **Related**: [ADR-0004](0004-offline-first-response-sync-via-client-ids.md), [ADR-0008](0008-survey-response-target.md)
- **Amends**: [ADR-0004](0004-offline-first-response-sync-via-client-ids.md) and
  [ADR-0008](0008-survey-response-target.md) — the survey response contract gains a
  second identity, human-facing and human-assigned, alongside the client-generated
  primary key. Neither ADR's sync or targeting rules change.

## Context

Field work is distributed by handing out **number ranges**. An analyst sends three
field workers out with the same survey and tells them: you take 1 through 50, you take
51 through 100, you take 101 through 150. Each paper form, each interview, each
response carries the number the field worker wrote on it. When the analyst later opens
the dashboard, "responses 51 to 100" *is* how they identify one field worker's batch,
how they notice that number 74 never arrived, and how they reconcile the digital record
against whatever the worker carried in a folder.

The system had no representation of this at all. A survey response is identified by a
UUID primary key (client-generated, per [ADR-0004](0004-offline-first-response-sync-via-client-ids.md)),
which is correct for sync idempotency and useless to a human holding a clipboard. The
`response_target` from [ADR-0008](0008-survey-response-target.md) anchors a response to a
subject or an establishment — but the `anonymous` target anchors it to nothing, and
those are precisely the surveys where a human-readable identifier matters most.

The obvious cheap move — model the number as one more question on the survey, of type
`numeric`, stored in the response's `answers` JSONB — was raised and rejected by the
product owner before this ADR was written. The reason is concrete and worth recording:
the number has to be **rendered in the mobile app's response history list**, where each
row today shows the survey, the target and the date. An answer inside JSONB cannot be
rendered there without loading the survey definition to find out which question is "the
number one", cannot be indexed, cannot be filtered on by range, and cannot be
constrained to be unique. The range assignment that makes the whole scheme work would
have no enforcement anywhere.

## Decision

**`survey_responses` carries a required `response_number`: a positive integer, entered
by hand by the field worker, unique within its survey.**

1. **Storage and shape.** A `NOT NULL` integer column on `survey_responses`, validated
   at the schema layer to the range `1`–`999999`. The cap is not arithmetic paranoia —
   it turns a date typed into the wrong field (`20250115`) into a `422` rather than a
   permanently wrong record.

2. **Uniqueness is per survey.** A unique index on `(survey_id, response_number)`. Not
   global (which would force coordination across unrelated campaigns) and not per field
   worker (which would make the number meaningless on its own in the dashboard, the one
   place it is read).

3. **A duplicate number is a `409` reusing `survey-response-already-exists`.** The
   conflicting response is named in the `existing_response` extension, which now also
   carries its `response_number`. The exception's detail is parameterized so the two
   conflicts it now represents read differently; the `type` URI is shared. In `submit()`
   the number check runs **after** the client-supplied-id replay check — so a retried
   sync is never a conflict against itself, exactly as
   [ADR-0008](0008-survey-response-target.md) established — and **after** the target
   conflict check, which wins when both apply. `SurveyResponseRepository.create` already
   reads the violated constraint's name off the driver error and maps it to a field; it
   gains a `response_number` case, and the service gains the matching branch that
   re-reads the conflicting row on the lost-read-race path.

4. **The number edits like an answer.** It is required in the edit request body, replaced
   under the same full-replace semantics as `answers`, permitted to the same actors
   (original submitter or admin/superadmin), re-checked for uniqueness unless unchanged,
   and governed by the same last-write-wins-by-`event_at` rule.
   `survey_response_edits` gains its own `NOT NULL response_number` so an audit snapshot
   stays a complete picture of the response after the edit.

5. **It travels everywhere a response does.** Returned in the standard response payload,
   the dashboard detail view, the dashboard listing item and the activity-feed item that
   backs the mobile history screen; written as a leading column in the XLSX
   exports. Filterable by exact value and by range on both the response listing and the
   export. **Not** sortable — no new sort orders. **Not** on the cross-survey analytics
   summary, where a per-survey number has no meaning.

6. **Range assignment stays outside the system.** No model of assigned ranges, no
   validation that a submitted number falls inside a range the field worker holds, no
   warning when it does not. The server accepts any positive integer not already taken
   in that survey. This is a deliberate non-decision, recorded so it is not mistaken for
   an oversight.

7. **One migration, existing rows renumbered.** Add the column nullable, backfill
   `row_number() over (partition by survey_id order by created_at, id)`, backfill each
   edit row from its parent response, `SET NOT NULL`, create the unique index — in a
   single revision, because the backfill without the constraint and the constraint
   without the backfill are each meaningless.

## Why not

**A `numeric` question inside `answers`.** The rejection that motivated this ADR; see
Context. It is the cheapest thing to build and the only one that cannot satisfy the
requirement.

**A server-assigned sequence.** The number's entire purpose is to correspond to a range
a human assigned offline, on paper, before the device was ever opened. A server counter
cannot know that range, so it would produce a number that matches nothing in the field
worker's folder — a second identifier as useless to a human as the UUID already is.

**Auto-reassigning the next free number on collision.** Tempting under offline-first,
since it never rejects data. Rejected: it silently rewrites a human-facing identifier,
and can hand a worker a number outside the range they were assigned, breaking the exact
property the analyst relies on. A rejection the worker can see and correct is better
than a correction they never learn about.

**A dedicated `duplicate-response-number` error type.** Recommended during the design
interview and declined by the product owner in favour of reusing the existing 409. See
Consequences for what this costs.

**Sorting by response number.** Offered and declined. The range filter covers the
workflow the analysts described; ordering a filtered range by number was judged
unnecessary.

**Extending the number to `talla_y_peso` measurements.** The same actors and the same
offline-sync shape make it an easy transplant, and it is deliberately not done here.
The column is named for what it is rather than generically, so replicating it later is
mechanical rather than a shared abstraction built on one example.

## Consequences

**A duplicate is discovered at sync time, possibly days late.** A field worker can
complete an interview offline with a number another worker already used and only learn
at sync. This is the same failure shape [ADR-0008](0008-survey-response-target.md)
accepted for duplicate targets, on the same endpoint, and the mobile client already has
to handle a late-arriving `409` there. Unlike the target conflict — which is terminal
for the second submitter — this one is recoverable: the worker changes the number and
resubmits.

**Two different conflicts now share one error type.** Reusing
`survey-response-already-exists` means a client cannot tell "this subject already
answered this survey" (unrecoverable; the response exists and belongs to someone else)
from "that number is taken, pick another" (recoverable inline) by the RFC 7807 `type`
URI alone. It must read the detail text, or infer from which fields it sent. This was
the product owner's explicit choice; if client implementations start string-matching the
detail, splitting the type is a backward-compatible addition.

**The column is `NOT NULL`, so every submitting client must send it.** There is no
transition period and no optional phase: an existing mobile build that does not send
`response_number` gets a `422`. Acceptable only because the service is pre-production —
the same condition [ADR-0008](0008-survey-response-target.md) relied on when it deleted
every historical response.

**Existing responses were renumbered arbitrarily.** The backfill assigns 1..N per survey
by `created_at`. Those numbers correspond to no paper form and no assigned range; they
exist to satisfy the constraint. This is fine because every affected row is test data,
and it is the reason the alternative — leaving legacy rows null — was not needed. A
`downgrade` drops the column and the index; the assigned numbers are not recoverable and
are not worth recovering.

**The constraint-name mapping introduced by ADR-0008 is now load-bearing for a third
case.** That ADR documents at length how attributing every `IntegrityError` to the
primary key produced a `500` where a `409` was specified, and how the violated
constraint's name has to be read from `error.orig.__cause__` under asyncpg rather than
from `diag`. Adding a third unique constraint to this table without extending that
mapping reproduces exactly that bug for duplicate numbers.

**The number is not a foreign key and not a target.** It does not participate in the
`num_nonnulls(subject_id, establishment_id) <= 1` check, does not affect
`response_target`, and is required identically for `subject`, `establishment` and
`anonymous` surveys — including FIES, whose responses are anonymous by
[ADR-0008](0008-survey-response-target.md) and therefore have no other human-readable
anchor at all.
