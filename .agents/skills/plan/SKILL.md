---
name: plan
description: >
  Explicit-only Phase 2 workflow for Ingeniería para la Alimentación. Invoke only through
  /plan or $plan to turn a Phase 1 research document into a cross-repo implementation plan.
  Never select this skill implicitly for ordinary planning requests.
---

# Plan Skill — Phase 2

Run this workflow only when the user explicitly invokes `/plan` or `$plan`.

You are performing Phase 2 of a structured feature-development workflow. Your job is to
produce a detailed, actionable implementation plan based on the Phase 1 research.
Do not implement anything — write a plan only.

A feature usually lands as **several PRs, one per repo**, in a deliberate order. Deciding that
order — and what each repo can ship without breaking the others mid-flight — is part of the
plan, not an afterthought for Phase 3.

## The repos and feature worktrees

```bash
bash .agents/scripts/feature-worktrees.sh require <N>-<feature-name> backend web mobile
bash .agents/scripts/feature-worktrees.sh list <N>-<feature-name>
```

`backend` (FastAPI, the worktree you are in), `web` (backoffice), `mobile` (app_mobile).
Use only the paths recorded for this numbered feature. Never fall back to a main checkout or
initialize a second worktree set during planning.

All plan artifacts live in the **backend** at `docs/plans/<N>-<feature-name>/`.

## Input

```
/plan <N>-<feature-name>
```

If the folder argument is missing, ask. If `docs/plans/<N>-<feature-name>/research.md` does
not exist, tell the user to run `/research` first.

## Step 1 — Read the research

Read `docs/plans/<N>-<feature-name>/research.md` in full. Understand:

- The current state across every repo in scope
- The DB schema and data flows
- **§6 Cross-Repo Contracts** — this drives the PR order
- **§7 Auth & Permissions** — who may reach the new flow
- The open questions and gaps flagged
- The dependencies and risks

Also read the conventions file of each repo in scope. For the backend that means `CLAUDE.md`
plus `docs/architecture.md`, `docs/conventions.md` and `docs/auth.md` — its layer rules are
strict and the plan must respect them:

| Layer | Responsibility | Must not |
|---|---|---|
| `app/api/<module>/` | Parse HTTP input, call services, return responses | Contain business logic or DB queries |
| `app/services/<module>/` | Business logic and domain rules | Access the DB directly or know about HTTP |
| `app/repositories/<module>/` | DB queries only | Contain business logic |
| `app/models/<module>/` | ORM model definitions | Contain methods with business logic |

For the mobile app read `CLAUDE.md` (CLEAN + MVVM, Koin, the six-file screen pattern, MingCute
icons, and the `AlTheme` design system). For the web app read `AGENTS.md`, `CLAUDE.md`, and
the relevant sections of `docs/architecture.md` and `docs/conventions.md`.

## Step 2 — Ask for context

Ask targeted questions about the gaps you actually found. Do not ask generic questions.

```
I've read the research. Before I write the plan, I need a few things:

**Open questions from research that affect the plan:**
1. [Quote the specific open question] — what's your answer?
2. ...

**Design & implementation context:**
- Do you have a Figma design, mockup, or screenshot for the web/mobile changes?
  (paste a link or describe what you want)
- Any specific library, pattern, or reference implementation you want to follow?
- Which roles (admin / analyst / field_worker) should reach this, and does it need
  per-establishment scoping?
- Any constraints I should know about (timeline, backward compatibility, mobile builds
  still in the wild that must keep working)?

**Rollout:**
- Should the API ship first and the clients follow in a later release, or do they land together?
- Anything here that needs to stay behind a flag?

**Extra context (optional):**
- Links to relevant docs, PRs, or tickets?
```

Wait for the user's response. Incorporate every answer into the plan.

## Step 3 — Determine which lanes to spawn

Spawn only the lanes the feature touches, mirroring the research lanes:

- **`api-data`** — Alembic migrations, ORM models, repositories, indexes, seed/reference data
- **`api-backend`** — services, routers, Pydantic schemas, domain rules, exceptions
- **`web`** — backoffice routes, components, swr hooks, services, zod schemas
- **`mobile`** — app_mobile data/domain/presentation, Koin DI, navigation
- **`cross-cutting`** — auth middleware, permissions, email, exporters, config, anything that
  cuts across the others

## Step 4 — Spawn agents in parallel

Spawn all lane agents in the same turn. Each writes to a temp file.

Agent prompt template:

```
You are writing a detailed IMPLEMENTATION PLAN for the "<feature-name>" feature.
Do NOT write actual code that runs. Write a planning document with code snippets
that are accurate enough to implement from.

Feature description: <description from research>
User's answers to open questions: <paste answers from Step 2>
Additional context provided: <paste any links, designs, constraints>

Your lane: <api-data | api-backend | web | mobile | cross-cutting>
Your repo: <repo-key> at <absolute path from feature-worktrees.sh>

Read the research document at:
<backend>/docs/plans/<N>-<feature-name>/research.md

Read your repo's conventions and follow them exactly (backend: `AGENTS.md`, `CLAUDE.md`,
`docs/conventions.md`, and `docs/architecture.md`; mobile: `CLAUDE.md`; web: `AGENTS.md`,
`CLAUDE.md`, and the relevant project docs).

Then write your section plan to:
<backend>/docs/plans/<N>-<feature-name>/plan-lane-<lane>.md

Your plan section must include:

### For every NEW file
- Full repo-relative path (and which repo)
- Purpose and why it needs to exist
- Complete illustrative implementation, accurate enough to adapt

### For every MODIFIED file
- Full repo-relative path (and which repo)
- What specifically changes and why
- A BEFORE / AFTER snippet for each change

### For your lane specifically

**api-data:**
- The Alembic migration: a NEW revision under `alembic/versions/`, with the `down_revision`
  set to the current head (check `alembic heads` — the history has merge revisions, so
  confirm there is exactly one head before branching off it). NEVER edit an existing
  migration in place. Write both `upgrade()` and a real `downgrade()`.
- Do not hand-wave `--autogenerate`: write the operations you expect (`op.create_table`,
  `op.add_column`, `op.create_index`, enum creation) so a reviewer can check them.
- The matching SQLAlchemy model under `app/models/<module>/`, declarative style, matching
  the surrounding files' conventions
- Index additions, with the query each one serves
- Repository methods: signature + body, async, returning ORM models or scalars — queries
  only, no business logic

**api-backend:**
- Pydantic schemas in `app/schemas/<module>/` (request and response, separate)
- The service method(s) in `app/services/<module>/` holding all business logic
- The route handler in `app/api/v1/`, thin: parse, call service, return. Mounted through
  `app/api/router.py` — never added directly to `app/main.py`
- Domain exceptions and how they map to the canonical error response
- Auth: which dependency/middleware guards the route, and which roles pass. Establishment
  permission checks stay centralized — never inline in the endpoint
- Which tests to add under `tests/unit/` and `tests/integration/`

**web (backoffice):**
- Route or page changes under `app/dashboard/…` (route segments are in Spanish; match them)
- Component structure (full TSX for new components), reusing `components/ui/` shadcn
  primitives before writing new ones
- Data fetching: the `services/<name>.service.ts` call plus the `hooks/use<Name>.ts` swr hook
- Zod schema in `schemas/<name>.schema.ts` for any form, wired via react-hook-form
- Types shared with the API contract in `lib/types.ts`

**mobile:**
- DTOs + mappers + repository impl in `data/<feature>/`, models + use cases + repository
  interfaces in `domain/`, and the Action / Destination / Navigation / Screen / State /
  ViewModel six-file set in `presentation/feature/<name>/` for any new screen
- Route registration in `presentation/navigation/Route.kt` and wiring in `app/AppNavHost.kt`
- Koin module registration in `di/`
- Reuse existing `core/design_system` composables and `AlTheme.colors/typography` tokens;
  flag anything genuinely new. Icons are MingCute vector drawables — never
  `androidx.compose.material.icons.*`

**cross-cutting:**
- Middleware or dependency changes, permission rules, email templates, export formats,
  configuration/settings additions

Include a Mermaid diagram if the new components introduce non-obvious interactions.
State explicitly which OTHER repos your lane depends on and what contract it needs from them.
```

Wait for all agents to complete.

## Step 5 — Synthesize into plan.md

Read the lane files, write `docs/plans/<N>-<feature-name>/plan.md`, delete the lane files.

---

```markdown
# Plan: <Feature Name>

> **Feature:** <one-line description>
> **Date:** <today's date>
> **Based on research:** docs/plans/<N>-<feature-name>/research.md
> **Repos:** backend, web, mobile
> **Worktree set:** <N>-<feature-name> (local paths in `.context/feature-worktrees/`)

## 1. Overview & Objective

What this feature does, why it's being built, and what "done" looks like.

## 2. Architecture Decisions & Trade-offs

Key decisions and why. What was considered and rejected. Constraints that shaped the plan.

## 3. Architecture Diagram

\`\`\`mermaid
flowchart TD
...
\`\`\`

## 4. PR Plan & Landing Order

One PR per repo, each based on `develop`. All three repos use `develop` for feature PRs;
`main` is release promotion only, and the backoffice enforces this in CI — PRs to `develop`
must come from `feat/*`, `fix/*`, `refactor/*`, `docs/*` or `chore/*`, and PRs to `main` may
only come from `develop`.

| # | Repo | Branch | Contains | Blocks | Safe to merge alone? |
| - | ---- | ------ | -------- | ------ | -------------------- |
| 1 | backend | `<current Conductor branch>` | migration + endpoint | web, mobile | yes — additive, no client reads it yet |
| 2 | web | `feat/<name>` | new page + swr hook | — | after #1 deploys |
| 3 | mobile | `feat/<name>` | new screen + use case | — | after #1 deploys |

Record the backend's actual branch without renaming it. Give each detached client worktree the
planned branch name; client branch names should match each other when their repositories allow it.

State for each PR **what makes it safe to land on its own**. The API PR normally lands and
deploys first and must be backward-compatible, because old clients stay in the wild — mobile
especially, where users do not update on your schedule.

Note any migration that must be applied before a client PR merges, and anything that has to
stay behind a flag until every client catches up.

## 5. Tasks Checklist

Ordered implementation tasks, grouped by lane, dependencies respected. Ticked off in Phase 3.

- [ ] 1. <first task>

## 6. DB Migrations

### New revision: `alembic/versions/<rev>_<slug>.py`

\`\`\`python
revision = "<rev>"
down_revision = "<current head>"

def upgrade() -> None:
    ...

def downgrade() -> None:
    ...
\`\`\`

### Model updates

\`\`\`python
# BEFORE
# AFTER
\`\`\`

### Notes

Applied with `poetry run alembic upgrade head`. Never modify the schema by hand and never edit
a merged migration in place — add a follow-up revision instead. Confirm `alembic heads` shows a
single head before setting `down_revision`; if the feature branches off a second head, plan the
merge revision explicitly.

## 7. API Changes (backend)

New files with full implementations; modified files as BEFORE/AFTER. Grouped by layer:
models → repositories → services → schemas → api. Note where each new route is mounted in
`app/api/router.py`, and which roles and establishment scoping apply.

## 8. Web Changes (backoffice) / 9. Mobile Changes

Same pattern, per repo. Omit the sections for repos not in scope.

## 10. Cross-cutting Changes

Auth, permissions, email, exports, config — only if applicable.

## 11. Validation

How anyone confirms this works, per repo. Use each repo's real commands:

| Repo | Commands |
| ---- | -------- |
| backend | `poetry run pre-commit run --all-files`, `poetry run pytest tests/unit/`, `poetry run pytest` (needs Docker), `poetry run alembic upgrade head` |
| web | `npm run lint`, `npm run typecheck`, `npm run build` |
| mobile | `./scripts/compile.sh`, `./gradlew :composeApp:testDebugUnitTest` |

Local-environment note for the backend: Poetry may not be on PATH
(`/Users/juanduzac/.local/bin/poetry`) and an unrelated venv is often active, so run it as
`env -u VIRTUAL_ENV poetry …`. Each worktree gets its own venv — `poetry install --no-root`
in a fresh workspace before concluding anything is broken. Integration tests need Docker
running (Testcontainers).

Plus the manual checks: the observable behavior to look for, and the edge cases.

New or changed backend logic needs tests — `tests/unit/` for services and pure logic,
`tests/integration/` for a new endpoint or repository query.

## 12. Out of Scope

What was explicitly NOT included and why.
```

---

## Step 6 — Self-check

Re-read plan.md and verify:

- Every open question from research.md is addressed, or explicitly deferred in §12
- Every file that needs to change has an entry, in the right repo
- The task checklist respects dependencies
- New files have full implementations; modified files have BEFORE/AFTER snippets
- The Mermaid diagram reflects the actual new architecture
- **§4 says why each PR is safe to land alone, and the API PR is backward-compatible**
- The backend layer boundaries hold: no business logic in routes or repositories, no DB
  access in services, no inline establishment permission checks
- The migration is a new revision with a correct `down_revision` and a real `downgrade()`
- §11 names real commands for every repo in scope

Fill anything missing before telling the user the plan is ready.

## Done

```
plan.md is ready at docs/plans/<N>-<feature-name>/plan.md.
It lands as <n> PRs: <repo> → <repo> → <repo>.

Review it and annotate inline with any corrections or questions.
When you're happy with it, we can move to Phase 3: Implementation.
```
