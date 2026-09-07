# ADR-0013: Survey response numbers are non-unique within a survey

- **Status**: Accepted
- **Date**: 2026-09-07
- **Deciders**: Backend team (product decision)
- **Related**: [ADR-0004](0004-offline-first-response-sync-via-client-ids.md),
  [ADR-0008](0008-survey-response-target.md),
  [ADR-0012](0012-manual-response-number-on-survey-responses.md)
- **Supersedes (in part)**: [ADR-0012](0012-manual-response-number-on-survey-responses.md)
  — specifically its per-survey response-number uniqueness and the duplicate-number
  conflict behaviour derived from that invariant.

## Context

ADR-0012 introduced a required, manually entered response number so field workers could
match a digital response to their own paper records. It made that number unique within a
survey, on the assumption that field workers' assigned ranges formed one shared sequence.

That assumption does not hold for the intended workflow. A response number is a personal
reference that a field worker uses to organise their records, not a shared identifier for
every response to a survey. Requiring uniqueness makes workers search for an unused number
because another worker used the same familiar label, even though neither response is
ambiguous in its own fieldwork context. Offline synchronisation can surface that rejection
well after the interview, creating unnecessary recovery work without improving response
identity: the client-generated UUID remains the identity and idempotency mechanism.

## Decision

`response_number` remains required, manually entered, positive, visible, editable,
filterable, and included in response exports. It is **not unique**, including within one
survey. Submitting or editing a response to a number already used by another response
succeeds normally.

The database keeps a non-unique B-tree index on `(survey_id, response_number)` for scoped
exact and range filters. An exact-number filter can therefore return multiple responses;
callers must treat it as a list filter, not an identifier lookup.

The system does **not** manage, assign, store, validate, or enforce field-worker number
ranges. It neither checks that a number belongs to a worker's range nor reports gaps or
overlaps in ranges. Such range administration would require a separate product decision
and data model.

The existing target uniqueness and client-id replay rules are unchanged. The
`survey-response-already-exists` conflict remains for the pre-existing target constraint;
response numbers no longer cause a conflict or a response-number conflict discriminator.

## Consequences

- Multiple responses in the same survey may carry the same number, including responses
  submitted by different workers.
- Exact and range filters, including XLSX exports, return every matching response. A
  number alone is not sufficient to select one response.
- The response-number audit snapshot remains useful as a record of what the submitter
  entered, but it does not assert a uniqueness invariant.
- A future per-worker uniqueness rule is out of scope. It would need an explicit decision
  about worker identity, offline behaviour, and range ownership rather than being inferred
  from this field.
