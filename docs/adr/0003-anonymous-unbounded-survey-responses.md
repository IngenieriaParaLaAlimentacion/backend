# ADR-0003: Survey responses are anonymous, individual, and unbounded per comedor

- **Status**: Superseded
- **Date**: 2026-07-10
- **Deciders**: Backend team (design interview with product owner)
- **Related**: `docs/plans/survey_response_registration.md`, [ADR-0001](0001-declarative-whole-survey-authoring-api.md), [ADR-0002](0002-fies-as-template-no-survey-type.md)
- **Superseded by**: [ADR-0008](0008-survey-response-target.md)

## Context

The response-registration user story ships with acceptance criteria that, taken
literally, describe a survey response as a **comedor-level aggregate**:

- CA2: "el sistema requiere que indique explícitamente a qué comedor está asociando
  esa respuesta" (singular: a comedor, not a person).
- CA5 (as written): "Respuesta única por combinación encuesta-comedor" — one response
  per survey+comedor, new submissions rejected once one exists.
- CA7 (email branch, as written): notify the submitting user by email whenever a
  response is created or finishes syncing.

During design review it became clear this doesn't match the real field workflow: a
relevador visits one comedor and interviews **multiple individual people** there, each
producing their own answers to the same survey. CA5's "one response per comedor" would
mean only the *first* person interviewed at a comedor could ever be surveyed — which
directly contradicts the actual process.

Two follow-up questions had to be resolved once the per-individual model was
established:

1. Should a response identify *who* was interviewed? The obvious candidate is the
   existing `Subject` entity (`app/models/subject.py`) — a DNI/PII-bearing person
   registry already used by `talla_y_peso` (Module 1) and already referenced from other
   services (`measurement_service.py`, `activity_repository.py`, `subject_service.py`,
   `admin_service.py`, `email_service.py`).
2. If responses are per-individual, what does "one response per survey+comedor"
   (CA5) even mean anymore?

## Decision

**Survey responses are anonymous, individual, and have no uniqueness constraint.**

- `SurveyResponse` has **no relationship to `Subject` at all** — not even an optional
  one. No DNI, no name, no demographic fields are captured on a response. This was
  considered and explicitly reversed during design (a nullable `Subject` FK was on the
  table, then dropped) — the product decision is that food-survey responses do not
  carry individual identity, full stop.
- **CA5's uniqueness constraint is dropped entirely.** Any number of responses may
  exist for the same `(survey_id, establishment_id)` pair — this is the expected shape
  of the data (N interviews per comedor visit), not an edge case to guard against.
  Aggregation/analysis across a comedor's responses for a survey is downstream
  (`dashboard` module) work, out of scope here.
- **CA7's email-notification branch is dropped entirely.** No email is sent on
  response creation or sync, in either the instant-sync or delayed-offline-sync case.
  `app/services/email_service.py` is not touched by this feature.

## Consequences

**Positive**

- Matches the real field workflow (N interviews per visit) instead of an aggregate
  model that would silently block legitimate data collection after the first response.
- No PII/consent burden on this module — `encuesta_alimentaria` responses carry no
  identity data, so this feature does not need to reason about `Subject` consent,
  DNI uniqueness, or cross-module coupling to `talla_y_peso`'s person registry.
- Removing the uniqueness constraint also removes an entire class of conflict-handling
  complexity that a comedor-level constraint would have forced onto the offline-sync
  design (see [ADR-0004](0004-offline-first-response-sync-via-client-ids.md)) — no
  "two people offline-submitted for the same comedor, who wins" problem exists, because
  there was never a uniqueness rule to violate.

**Negative — deliberate acceptance-criteria deviations**

- **CA5 is not implemented as written.** There is no "respuesta única por
  combinación encuesta-comedor" rule, and no reject-then-redirect-to-edit flow for a
  duplicate submission. If a future requirement needs per-respondent uniqueness (e.g.
  "the same person can't answer the same FIES instrument twice in a reference period"),
  it would require introducing *some* respondent identifier — which is explicitly not
  present today. The escape hatch is the same shape as ADR-0002's: add an identifier
  concept (nullable `Subject` FK, or a lighter non-PII per-respondent token) later if
  this becomes a real requirement.
- **CA7's email-confirmation requirement is not implemented.** If a future requirement
  needs submission confirmation, it would be a net-new addition (there is no partial
  implementation to build on).
- **Responses cannot be attributed to a person for individual-level follow-up or
  cross-referencing with `talla_y_peso`/`valores_de_hierro` records.** Only aggregate,
  comedor-level analysis is possible from this data. This is an accepted trade-off, not
  an oversight — see Context above.

## Alternatives considered

**Nullable `Subject` FK, relevador's choice per submission** — link a response to an
existing `Subject` record when the relevador chooses to identify the respondent, leave
it `NULL` for anonymous responses. Considered and initially agreed on, then explicitly
reversed: no partial-identity mode was actually wanted; every response is anonymous.

**Per-survey identification policy** (survey author decides if responses must/may/must
not carry an identity) — rejected as an unnecessary axis of configuration for a
requirement that, in practice, always resolves to "anonymous."

**Uniqueness scoped to `(survey_id, establishment_id, subject_id)`** — the natural
constraint if responses *did* carry identity. Moot once `Subject` linkage was dropped;
documented here only because it was the design's intermediate state and explains why
CA5 could not simply be "fixed" by adding a third column to the unique key.
