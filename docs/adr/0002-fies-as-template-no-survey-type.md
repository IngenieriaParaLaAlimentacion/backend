# ADR-0002: FIES as a seed template, with no persistent survey `type`

- **Status**: Accepted, amended
- **Date**: 2026-07-06
- **Deciders**: Backoffice / backend team
- **Related**: `docs/plans/survey_authoring.md`, [ADR-0001](0001-declarative-whole-survey-authoring-api.md)
- **Amended by**: [ADR-0007](0007-survey-response-target.md) — the core decision (FIES is a
  seed template, not a survey type) still holds. ADR-0007 only records that the template
  now also seeds `response_target: anonymous`, and revisits the `instrument_type` escape
  hatch this ADR anticipated.

## Context

The user story frames surveys as having a **type**: *"tipo (FIES o personalizada)"*
(CA1), and CA4 gates question-editing on that type
(*"Dado que una encuesta es de tipo personalizada … su responsable agrega, edita o
elimina preguntas"*) — i.e. as literally written, a FIES survey's questions would be
**non-editable**, and a custom survey's questions editable.

FIES is the FAO **Food Insecurity Experience Scale**: a standardized 8-item instrument.
The product intent, clarified during design, is that FIES should act as a **quick-start
template** — admins create a survey pre-filled with the FIES questions and are then free
to **add and adjust** questions — rather than as a locked, separate kind of survey.

## Decision

**Do not model a persistent `type` field.** FIES is a **read-only seed template**, not a
survey classification.

- `GET /surveys/templates/fies` returns the canonical FIES 8-item structure (8
  `single_choice` questions, "Sí"/"No" options, all required) from
  `app/data/fies_template.py`.
- The client pre-fills the builder with that payload and submits a **normal**
  `POST /surveys`. The server does not special-case FIES at creation.
- The resulting survey has **no type**; its questions are ordinary rows, fully editable
  like any other survey's (bounded only by the 1–30 rule and the edit-lock).

## Consequences

**Positive**

- Simpler data model — no `type` column, no per-question origin flag.
- The three CA1 creation paths (from scratch / from FIES template / by duplication)
  collapse onto one create path that differs only in seed data.
- FIES-seeded surveys are extensible: admins can add their own questions around the
  standard items, which is the stated goal.

**Negative — deliberate acceptance-criteria deviations**

- **Loosens CA4**: because there is no `type`, **every** survey is editable. FIES-seeded
  questions can be edited or deleted. This is an accepted trade-off.
- **FIES scoring/analytics is not reliably identifiable.** Since nothing marks a survey or
  its questions as canonical FIES, a future FIES score on the dashboard would have no
  dependable way to recognize FIES data. Re-introducing an origin marker
  (e.g. `origin = 'fies'` per question, or a survey-level flag) is the escape hatch if
  FIES scoring becomes a requirement.
- **CA8 is deferred**: the structural edit-lock is built only as a forward-compatible stub
  behind `response_count` (always 0 until response collection ships), so only **CA7** is
  fully enforced today. See `docs/plans/survey_authoring.md` and ADR-0001.
