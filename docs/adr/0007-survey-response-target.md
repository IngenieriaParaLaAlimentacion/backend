# ADR-0007: A survey declares what its responses are about — subject, establishment, or nobody

- **Status**: Accepted
- **Date**: 2026-08-14
- **Deciders**: Backend team (design interview with product owner)
- **Related**: `docs/plans/survey_response_target.md`, [issue #95](https://github.com/IngenieriaParaLaAlimentacion/backend/issues/95)
- **Supersedes**: [ADR-0003](0003-anonymous-unbounded-survey-responses.md)
- **Amends**: [ADR-0002](0002-fies-as-template-no-survey-type.md) — FIES stays a seed
  template rather than a survey type; only the value it seeds changes.

## Context

Two different questions had been collapsed into one field.

`Survey.scope` (`generic` / `targeted`) plus the `survey_establishments` join table
answered **"which establishments' field workers may see this survey"** — a
*distribution* rule. Every `SurveyResponse` then carried a mandatory
`establishment_id`, which served simultaneously as the response's only real-world
anchor and as the thing authorization was checked against.

Neither matched what the product actually needed. Surveys are now used in three
distinct ways: some are answered **about a person** (and should join against that
person's height/weight history from Module 1), some **about a comedor**, and some
about **nobody trackable at all**. And field workers can now register without any
establishment — they may sign up purely to answer surveys — so gating survey
visibility on establishment membership locks out the very users the feature exists
for.

## Decision

**Replace `scope` with `response_target`**: an enum of `subject`, `establishment`,
`anonymous`, declared at creation, describing what each response is *about*.

1. **Distribution is gone entirely.** `scope`, the `surveyscope` type, the
   `survey_establishments` table and `Survey.establishments` are dropped.
   `is_active` becomes the only visibility rule, for every role.
   `GET /surveys/available` returns all active surveys to every field worker.

2. **The establishment on a response is data, not permission.** Three checks are
   deleted: the survey path's establishment-access check, the field-worker
   view check's audience branch, and the survey-scope assertion on submit. Any
   field worker may answer for any establishment. (The `is_active` half of the
   view check is kept, so deactivated surveys stay hidden.) The equivalent check
   in `talla_y_peso` is untouched.

3. **`survey_responses` carries two nullable FKs** — `subject_id` and
   `establishment_id`, both `ON DELETE RESTRICT` — with a `CHECK` allowing at most
   one. Which one is *required* depends on the survey's `response_target` and is
   enforced in the service. Anonymous responses have neither.

4. **A target answers a given survey once.** Two partial unique indexes,
   `(survey_id, subject_id)` and `(survey_id, establishment_id)`, each
   `WHERE ... IS NOT NULL`. Anonymous surveys stay unbounded.

5. **`response_target` is locked once a survey has responses**, alongside the
   existing structural edit-lock.

## Why not

**Two nullable FKs over a generic `(target_type, target_id)` pair.** Postgres
cannot express a polymorphic foreign key, so the generic form would trade real
referential integrity for flexibility we have no roadmap for. This data feeds a
health dashboard; dangling references are a real cost.

**No new "survey respondent" entity.** Reusing `Subject` is the point — it is what
lets a survey response be analyzed against that person's measurements. Its
mandatory unique `dni` is a known constraint for people without documents; relaxing
it is a separate product decision affecting Module 1.

**No `SubjectEvent` written for subject-targeted responses.** The link is for
analytics and export today; nothing in the product shows a person's own timeline of
survey responses. Worth revisiting when such a view exists.

## Consequences

**Anonymous and subject-targeted responses have no geography.** The city, province and
establishment filters all resolve through the response's `establishment_id`, so all
three are rejected with a `400` (`InvalidListingFilterError`) on surveys that do not
target establishments — on both the response listing and the export — rather than
silently returning an empty page or workbook, which is indistinguishable from "no data
matched". The global analytics summary keeps its establishment join, where matching only
establishment-linked responses is the correct reading.

**`participating_establishments_count` is `0`** for subject and anonymous surveys.
That is literally true and was left alone; renaming it would break a field the
backoffice already consumes.

**A duplicate target is terminal for the second submitter.** It returns `409` with
an `existing_response` extension naming who answered and when, but response edits
remain owner-or-admin — so a second field worker rejected for a comedor cannot
correct the first one's answer without an admin. Combined with the deliberate
absence of a pre-flight check, a worker can complete an interview offline and only
discover the conflict at sync time. Accepted as the cost of the one-response rule.

**Constraint violations must be told apart.** `SurveyResponseRepository.create`
previously attributed every `IntegrityError` to the primary key — correct only
while the primary key was the table's sole unique constraint, which these indexes
end. Left alone, a target collision would be mislabelled as an id collision, the
service's replay lookup would find nothing, and the error would escape as an
unhandled `500` rather than the 409 this ADR specifies. The repository now reads the
violated constraint's name off the driver error and maps it to the field that actually
collided, and `submit()` checks the client-supplied id **before** the uniqueness rule so
a retried sync is never reported as a conflict against itself.

Where that name lives is driver-specific and easy to get wrong: `diag.constraint_name`
is a psycopg2 shape, while this service runs on asyncpg, whose adapter re-raises a
synthesized wrapper — leaving `error.orig` with only a message and the real
`UniqueViolationError` at `error.orig.__cause__`. Reading only `diag` returns `None`,
falls back to `"id"`, and reproduces exactly the `500` described above; the first draft
of this change did. `_violated_constraint` checks both, and an integration test blinds
the service's pre-check so the index path — the one a real race takes — is exercised
against Postgres rather than only against mocks.

**The client-supplied id is scoped to one survey.** Replaying an id under a different
`survey_id` would otherwise return the first survey's answers with a `200` and skip the
second survey's uniqueness rule entirely. It is a `400`.

**Historical responses were deleted.** `establishment_id` changed meaning from
"collected at" to "answered by", so existing rows could not be reinterpreted. The
migration deletes every `survey_responses` row, resets `surveys.response_count` to
zero, and leaves existing surveys as `anonymous`. Acceptable only because the
service was pre-production with test data alone; `downgrade` restores the schema but
not the data.

## What this changes from the superseded ADRs

**ADR-0002** decided FIES would be a template with no persisted type marker. An
`instrument_type` column was added later anyway (migration `76b6f29d84d0`) to drive
scoring, which the ADR had anticipated as the escape hatch. It remains a plain
client-supplied field: nothing validates that a survey flagged `fies` actually
contains the FIES items. The template now also returns
`response_target: anonymous`, because FIES measures food insecurity at the level of
a **household** — which is neither a `Subject` nor an `Establishment`. A fourth
`household` target is a known open question, deliberately out of scope here.

**ADR-0003** decided responses would be anonymous, have no relationship to `Subject`
"not even an optional one", and be unbounded per comedor. All three no longer hold:
subject-targeted surveys link to a person by design, and both subject- and
establishment-targeted surveys reinstate the uniqueness constraint that ADR dropped.
Its reasoning still holds for the `anonymous` target, which remains exactly what it
described.

**Identity now reaches the export.** A subject-targeted XLSX export includes name,
last name and DNI, which ADR-0003 explicitly excluded. The endpoint remains
restricted to `admin`/`analyst`/`superadmin`.

## Known dependency

Issue [#89](https://github.com/IngenieriaParaLaAlimentacion/backend/issues/89) is
unresolved: a field worker can register without establishments, but
`AdminService.approve_establishments` still welds account activation to approving at
least one, and there is no plain "approve account" endpoint. Until it lands, the
unattached field workers this ADR is written for cannot log in at all.
