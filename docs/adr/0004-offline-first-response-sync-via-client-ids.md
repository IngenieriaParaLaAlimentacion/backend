# ADR-0004: Offline-first response sync via client-generated primary keys

- **Status**: Accepted
- **Date**: 2026-07-10
- **Deciders**: Backend team (design interview with product owner)
- **Related**: `docs/plans/survey_response_registration.md`, [ADR-0003](0003-anonymous-unbounded-survey-responses.md)

## Context

CA7 requires the mobile app to register survey responses while offline and sync them
automatically once connectivity returns, "sin pérdida ni duplicación de datos." Since
[ADR-0003](0003-anonymous-unbounded-survey-responses.md) removes CA5's uniqueness
constraint, **client-generated-id idempotency is the only duplicate-prevention
mechanism** for responses — it has to be correct on its own, not a backstop for a
uniqueness constraint that no longer exists.

The codebase already has a working offline-first pattern, but it is **not** a separate
`idempotency_key` column — that was an inaccurate description surfaced during initial
research and corrected against the actual code. The real, working pattern is: the
client may supply the entity's own **primary key** as a UUID; if provided, the server
uses it as the row's `id` (making repeated submissions of the same `id` naturally
idempotent — an insert conflict on a known `id` means "already applied, return the
existing row"); if omitted, the server generates one. See:

- `app/schemas/measurement_schema.py:24-31` (`MeasurementRequest.id`)
- `app/schemas/subject_schema.py:22-29` (`SubjectRequest.id`)
- `app/services/measurement_service.py:55-98` (`MeasurementService.register` — the
  full idempotent-create implementation: check-by-id, create, catch
  `UniqueConstraintError` on a racing concurrent insert of the same `id`, replay as a
  200 instead of erroring)

Edits (CA6) need the same property — a retried edit-sync must not double-apply or
double-log — but an edit isn't a new "entity" with its own natural primary key the way
a response is; it's a mutation event against an existing response.

## Decision

**Reuse the client-generated-primary-key pattern for both response creation and
response edits — no new `idempotency_key` column anywhere.**

- `SurveyResponse.id`: client-generatable, exactly like `Measurement.id` /
  `Subject.id`. `POST /survey-responses` accepts an optional `id`; a repeat submission
  of the same `id` returns the existing response (200) instead of creating a duplicate
  or erroring.
- `survey_response_edits` (the append-only edit-audit table from the plan) also has a
  **client-generatable `id`**, populated by the client per edit-attempt. A retried edit
  sync with the same `id` is recognized as already-applied and no-ops (returns current
  state) rather than re-appending a duplicate audit row or re-applying the edit.
- Two timestamps, matching the `Measurement.measured_at`/`created_at` split: `event_at`
  (client-supplied — when the relevador actually finished answering/editing, which may
  be well before the device reconnects) and `created_at` (server-assigned persistence
  time). CA4's "fecha y hora de la carga" is satisfied by `event_at`.
- **Concurrent-edit conflicts are resolved last-write-wins by `event_at`, not by sync
  arrival order.** If two edits to the same response are made offline on different
  devices before either syncs, both still land in `survey_response_edits` (nothing is
  silently discarded), but the response's *current* `answers`/`event_at` are only
  overwritten when the incoming edit's `event_at` is `>=` the response's current
  `event_at`. An edit that arrives at the server late but was made earlier in wall-clock
  time does not clobber a more-recent edit that already synced. No rejection, no merge
  UI, no `409` — this is a deliberately cheap comparison, not conflict-detection
  machinery, justified by edits already being restricted to the original submitter or
  an admin (a narrow set of actors, making true concurrent edits rare).

## Consequences

**Positive**

- No new sync primitive invented — this is the third module (`talla_y_peso`'s
  `Subject`/`Measurement`, now `encuesta_alimentaria`'s `SurveyResponse`) to use the
  exact same client-generated-id mechanism, so mobile client code that already
  implements offline queuing/retry for measurements needs no new concept, just a new
  entity type to apply it to.
- The "second submitter loses the uniqueness race" scenario that motivated an earlier,
  more complex conflict-handling design entirely disappears once combined with
  ADR-0003 — there is no uniqueness constraint to race against, so a retried create is
  either "exact same `id`, already applied" (idempotent no-op) or "genuinely a new
  response" (always accepted). No 409s, no client-side orphaned-draft handling needed.
- `event_at`-based last-write-wins for edits is O(1) per edit (one comparison), not a
  new subsystem.

**Negative**

- Silent data supersession: if two legitimate edits to the same response conflict, the
  earlier one (by `event_at`) is never surfaced as "current" even though it's preserved
  in `survey_response_edits`. Recovering it requires manually inspecting the audit
  table; there is no UI for it in this ticket. Acceptable given the narrow edit-actor
  set (ADR context), but a known gap if edit contention turns out to be more common
  than expected.
- Two different `id`s now carry idempotency semantics for the same logical response
  (`SurveyResponse.id` for creation, `survey_response_edits.id` per edit) — a client
  implementation bug that reuses one for the other would silently misbehave (e.g. an
  edit retried with the *response's* `id` instead of a fresh edit-attempt `id` would
  collide with nothing and double-apply). Client-side discipline is required; this is
  the same shape of risk the `Measurement`/`Subject` pattern already carries and
  accepts.

## Alternatives considered

**Separate `idempotency_key` unique column** (distinct from the primary key) — this was
the initial framing during design, based on an inaccurate read of the codebase (there
is no such column on `Measurement` today). Rejected once the actual pattern was found:
it would have been a second, parallel idempotency mechanism alongside the
already-established client-generated-`id` one, for no added benefit.

**Reject conflicting edits with `409`, force client to redo against latest state** —
considered and rejected as unnecessary machinery given how few actors can edit a
response at all (ADR context); last-write-wins-by-`event_at` was judged sufficient.
