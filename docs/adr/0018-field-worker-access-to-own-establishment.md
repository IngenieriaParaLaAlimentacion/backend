# ADR-0018: Field worker access to their own establishment's reads

- **Status**: Accepted
- **Date**: 2026-09-19
- **Deciders**: Backend team
- **Related**: ADR-0009 (generic CSV exporter for listings), ADR-0008 (survey response target),
  ADR-0007 (establishment request review flow), ADR-0014 (materialized food stock)

## Context

Until this change, every establishment-scoped *aggregate* read was restricted to admins and
analysts, and the only reads open to a field worker were the two stock ones. The food-movements
user story broke that line: a field worker records intakes and outflows all day, and could not read
back what they had recorded, nor see when their own comedor last received food.

This is the first ADR about roles and permissions, so it also fixes the vocabulary. Four guards
exist in `app/core/dependencies.py`:

| Guard | Roles |
| --- | --- |
| `require_admin` | admin, superadmin |
| `require_admin_or_analyst` | admin, analyst, superadmin |
| `require_any` | every authenticated role, field workers included |
| `get_optional_actor` | no role requirement; the actor may be absent |

A guard answers "which roles may call this endpoint at all". It does **not** answer "which
establishments may this caller read", because the access token carries a role but no establishment
scope — per-establishment rights live in `user_establishments` and are resolved at request time by
`check_establishment_access` (`app/services/access.py`). That helper is a no-op for admins and
analysts, who work across every establishment by definition of their role, and for a field worker
requires an **approved** relation. ADR-0007 made that approval a deliberate, separate act, so the
requirement is not trivially satisfied.

Three pressures forced the decision now:

1. **A worker could write but not read.** `POST /food-intakes` and `POST /food-outflows` are open to
   field workers; every read built on top of them was not.
2. **The user story asked for it explicitly.** "Accesible por cualquier rol autenticado con acceso
   al establecimiento, igual que el resto de las vistas de stock — no restringido a admin/analista."
3. **The metric had nowhere else to live.** `last_intake_at` / `last_outflow_at` belong next to
   `last_measured_at` in the dashboard's `metrics`, and that endpoint was admin-only.

## Decision

### Opening an endpoint means `require_any` **and** `check_establishment_access`

This is the rule this ADR fixes. For an establishment-scoped read, widening the guard alone is not
opening the endpoint to field workers — it is opening it to *all* field workers, for *every*
establishment in the system. The two changes are one act:

- the route takes `actor: UserActor = Depends(require_any)` and passes the actor down, rather than
  discarding it with `_`;
- the service calls `check_establishment_access` after resolving the establishment, so an unknown id
  is a 404 and a denied actor a 403, in that order.

`GET /establishments/{id}/dashboard` had no actor threaded through it at all: its service took no
`UserActor` and never consulted `user_establishments`, because `require_admin_or_analyst` made the
question moot. Opening it required adding the check, not just changing the dependency.

### What is open to a field worker, and what is not

| Endpoint | Guard | Membership check |
| --- | --- | --- |
| `GET /establishments/{id}/stock` | `require_any` | yes |
| `GET /establishments/{id}/stock/export` | `require_any` | yes |
| `GET /establishments/{id}/food-movements` | `require_any` | yes |
| `GET /establishments/{id}/food-movements/{movement_id}` | `require_any` | yes |
| `GET /establishments/{id}/dashboard` | `require_any` | yes |
| `GET /establishments/{id}/subjects` | `require_admin_or_analyst` | — |
| `GET /establishments/{id}/subjects/export` | `require_admin_or_analyst` | — |
| `GET /establishments/{id}/field-workers` | `require_admin_or_analyst` | — |

The first two predate this work; the next three are what this PR adds. The last three stay closed,
and the line between the two halves is **aggregate versus identified**:

- `/subjects` and `/subjects/export` return, per row, a named minor's `dni`, `name`, `last_name`,
  `birth_date` and `sex`, together with their weight, height, BMI, nutritional status and clinical
  alerts. That is identifiable health data about children.
- `/field-workers` returns colleagues' `email`, their account status and their per-person
  measurement counts — including relations that were *rejected*.
- The dashboard returns counts, averages and a status distribution. No individual is named.

### The dashboard payload is not split by role

A field worker sees the same `EstablishmentDashboardResponse` an analyst sees. Splitting it would
mean two shapes for one endpoint and a contract that changes with the caller, for a payload that
names nobody.

## Consequences

*Positives*

- A field worker can read back what they recorded, and see their comedor's state, without an admin.
- The guard taxonomy and the "guard plus membership check" rule are written down; the next
  establishment-scoped endpoint has a pattern to copy instead of a precedent to guess at.
- The membership check closes a gap that was latent rather than new: had anyone widened the
  dashboard guard without it, every field worker would have read every comedor's figures.

*Negatives*

- The dashboard publishes an establishment's malnutrition prevalence to anyone enrolled there. It
  identifies nobody, but with a small `subject_count` — in the same payload — a `distribution` row
  of `count: 1` is effectively re-identifiable by someone who knows who attends. We accept this:
  the alternative is withholding from a worker the aggregate picture of the children they weigh.
- `EstablishmentDashboardService` now has one method that takes an actor and three that do not,
  which reads as an inconsistency until the other three are opened or explicitly closed.

*Neutral*

- Admins and analysts are unaffected: `check_establishment_access` returns immediately for them.
- Nothing changes for write paths; intakes and outflows were already open to field workers.

## Alternatives considered

**Putting `last_intake_at` / `last_outflow_at` on `GET /establishments/{id}`** — rejected. That
endpoint is already `require_any`, so it would have delivered the metric with no permission change
at all. But it returns an establishment's static identification block, and mixing a computed,
mutable value into it would have made a cheap catalog read into an aggregate query, and put the same
"when did this comedor last receive food" fact in a different place from "when was it last measured".

**Widening the guard without the membership check** — rejected, and worth naming because it is the
cheap version of this change and it is what a reviewer would not notice. `require_any` on a route
whose service ignores the actor lets any authenticated field worker read any establishment.

**Opening all four dashboard routes** — rejected. "A worker should know what happens in their own
comedor" does not extend to a colleague's email or to a named child's DNI and clinical alerts.

**Serving a reduced payload to field workers** — rejected. It splits one response schema into two
and versions the contract by role, to hide aggregates that name no one.

**Treating establishment membership as data rather than permission** — rejected here. ADR-0008 took
exactly that route for surveys: "any field worker may answer for any establishment", because a
survey response is data the worker *contributes*. That ADR was careful to note the equivalent check
in `talla_y_peso` was untouched. The dashboard sits on that module and is the opposite case: a read
of other people's data about identifiable minors, aggregated. Contributing to an establishment you
do not belong to is recoverable; reading it is not.

**Reading ADR-0009 as forbidding this** — considered and rejected. ADR-0009 restricted all five
exports to admin/analyst on the grounds that "exporting a whole padrón is a reporting action rather
than a lookup", and deliberately narrowed two views that were otherwise more open. That reasoning is
untouched here — `/subjects/export` stays closed — and its own distinction is the argument for this
change: an aggregate dashboard of one's own comedor is a lookup, not a report.
