---
name: research
description: >
  Phase 1 of the feature development workflow. Use this skill whenever the user invokes /research
  or asks to research, investigate, or understand the codebase before building a feature.
  Triggers on: "research [feature]", "investigate [feature]", "/research", "phase 1",
  "understand how X works before I build", "map out the current flow for".
  Creates docs/plans/[N]-[feature-name]/research.md with a deep analysis of the current flow
  across every Ingeniería para la Alimentación repo the feature touches — the FastAPI backend,
  the backoffice web app and the Compose Multiplatform mobile app — without touching
  implementation. Use this skill even if the user just says "I want to research X" or
  "let's do phase 1 for X".
---

# Research Skill — Phase 1

You are performing Phase 1 of a structured feature-development workflow. Your only job here
is to deeply understand the _current_ system as it relates to the feature being planned.
Do not suggest changes, do not implement anything, do not write any code. Just understand
and document.

Ingeniería para la Alimentación is one product across three repos. A feature is rarely
confined to one of them — the backend is the sole orchestrator (LLM calls, image/audio
processing, external storage) and both clients reach it only through the REST API — so
research spans every repo it touches. The resulting document is the shared brief that
Phase 2 plans against and Phase 3 builds from.

## The repos and feature worktrees

Every numbered research folder owns one stable set of worktrees. The backend path is the
current Conductor workspace; web and mobile are dedicated detached worktrees created from
`origin/develop`. Never research against or edit the main client checkouts.

Use `.agents/scripts/feature-worktrees.sh` to initialize and resolve the set. It records the
local mapping under `.context/feature-worktrees/`, so research, plan, and implementation all
use the same paths without committing machine-specific absolute paths.

| Key | Repo | What lives there |
| --- | ---- | ---------------- |
| `backend` | `backend` (the worktree you are in) | FastAPI, SQLAlchemy async, `alembic/versions/` (**source of truth for all DDL**), `app/{models,repositories,services,api,schemas}/<module>/` |
| `web` | `backoffice` | Next.js 16 App Router, React 19, Tailwind 4 + shadcn, `app/dashboard/*` routes in Spanish, `services/*.service.ts`, `hooks/use*.ts` (swr), `schemas/*.schema.ts` (zod) |
| `mobile` | `app_mobile` | Compose Multiplatform (Android + iOS), Kotlin, CLEAN + MVVM under `composeApp/src/commonMain/kotlin/ar/com/ingenieriaalimentacion/{data,domain,presentation}`, Koin DI |

Plans and research always live in the **backend**, at `docs/plans/<N>-<feature-name>/`,
regardless of which repos the feature touches. The backend is the coordination point;
the clients get PRs.

## Input

```
/research <feature-name> <short description of the feature>
```

If the feature name or description is missing, ask before proceeding.

## Step 1 — Determine folder number

Look at the existing folders inside `docs/plans/` in the backend and find the highest numeric
prefix (e.g. `1-food-catalog`, `2-receipt-intake` → next is `3`). The output folder is
`docs/plans/<N>-<feature-name>/research.md`. If `docs/plans/` is empty or has no numbered
folders, start at `1`.

Note: `docs/plans/` may also contain legacy single-repo plans as flat `.md` files. Ignore
those when numbering — count only the numbered directories.

Initialize all three worktrees immediately after choosing the folder name:

```bash
bash .agents/scripts/feature-worktrees.sh init <N>-<feature-name>
bash .agents/scripts/feature-worktrees.sh list <N>-<feature-name>
```

This is part of creating a research folder even when initial scoping suggests that only one
client will change. It gives later research and implementation lanes isolated, predictable
paths and lets them run concurrently. If initialization fails, stop before writing research.

## Step 2 — Confirm scope

1. Identify the candidate files across **every** repo. Think broadly: Alembic migrations,
   ORM models, repositories, services, routers, Pydantic schemas, exceptions, middleware,
   Next.js routes, service clients, swr hooks, zod schemas, Compose screens, view models,
   use cases, DTOs, Koin modules.

2. Decide which lanes the feature actually touches, and assign every file to exactly one.
   **Spawn only the lanes with real work** — an idle agent costs tokens and returns noise.

   | Lane | Scope |
   | ---- | ----- |
   | `api-data` | `alembic/versions/`, `app/models/<module>/`, `app/repositories/<module>/`, indexes, constraints, `app/reference_data/` seeds |
   | `api-backend` | `app/services/<module>/`, `app/api/v1/`, `app/schemas/<module>/`, `app/domain/`, `app/exceptions/` |
   | `web` | backoffice: `app/` routes, `components/`, `hooks/`, `services/`, `schemas/`, `lib/`, `context/` |
   | `mobile` | app_mobile: `data/` (DTOs, mappers, clients, repo impls), `domain/` (models, use cases, repo interfaces), `presentation/feature/<name>/`, `di/`, `core/design_system/` |
   | `cross-cutting` | auth + establishment-permission middleware, email, exporters, `app/config/`, `app/core/`, anything that cuts across the others |

   A file that bridges layers goes to whichever lane reads it most.

3. Present the plan to the user — lanes, files, and which repos will be in scope:

   ```
   Output: docs/plans/4-iron-values/research.md

   Repos in scope: backend, mobile   (web: not touched)

   Lane api-data:
   - alembic/versions/eb850f66c679_add_subjects_constraints_and_indexes.py
   - app/models/measurements/measurement.py
   ...

   Lane mobile:
   - /Users/.../app_mobile/composeApp/src/commonMain/kotlin/.../presentation/feature/measurement/
   ...

   Does this look right? Any files or repos to add or move?
   ```

4. **Wait for the user's confirmation before proceeding.**

## Step 3 — Parallel research

Spawn all lane agents **in the same turn** so they run in parallel. Each agent gets its file
list, the feature context, its repo's absolute path, and an output instruction.

Agent prompt template:

```
You are performing deep codebase research for a feature called "<feature-name>".
Feature description: <description>

You are researching the <lane> lane, which lives in the <repo-key> repo at:
<absolute path from feature-worktrees.sh path <folder> <repo-key>>

Read that repo's `AGENTS.md` first when present, then follow any project documentation it points to.
(Backend: also read `CLAUDE.md`, `docs/architecture.md`, `docs/conventions.md`, and
`docs/auth.md`. Mobile: read `CLAUDE.md`. Web: read `CLAUDE.md` plus the relevant sections
of `docs/architecture.md` and `docs/conventions.md`.)

Your job is to read and deeply understand the following files. Do not skim.
Understand what each piece does, how it connects to the others, and what the
current state looks like before this feature exists.

Files to research:
<list, absolute paths>

Write your findings as structured markdown to:
<backend>/docs/plans/<N>-<feature-name>/research-lane-<lane>.md

Include for each file:
- What it does and why it exists
- The full DB table definition (if applicable) with all columns, types, constraints
- The most important code snippets that reveal *how* it works
- How it connects to the other files in your list
- Every cross-repo edge you can see: the exact endpoint path, HTTP method and
  request/response shape where this lane hands off to another repo

Do not implement anything. Do not suggest changes. Research only.
```

Wait for all agents to complete before proceeding.

**On DB facts:** `alembic/versions/` is the source of truth for DDL, but the ORM models in
`app/models/` are what the code actually reads and the two can drift — the history has merge
revisions and hand-written migrations. When a table's live shape matters, reconcile the model
against the migration chain (`alembic history`, `alembic heads`) and say in the document which
one you trusted and why.

**On the API contract:** `docs/api.md` and the generated OpenAPI (`docs/generate_openapi.py`
in the backend, `docs/backend.openapi.generated.json` in mobile) are the fastest way to read
the current contract, but they are generated artifacts — verify anything load-bearing against
the actual router in `app/api/v1/` and note when the generated copy is stale.

## Step 4 — Synthesize into research.md

Read the lane output files, write the consolidated document at
`docs/plans/<N>-<feature-name>/research.md`, then delete the lane files.

Use this structure:

---

```markdown
# Research: <Feature Name>

> **Feature:** <one-line description from the user>
> **Date:** <today's date>
> **Repos in scope:** backend, web, mobile
> **Worktree set:** <N>-<feature-name> (local paths in `.context/feature-worktrees/`)
> **Backend commit:** <short sha> on <branch>

## 1. Overview — Current State

A narrative description of how this part of the product works today, as if explaining it to a
new team member. Follow the flow across repo boundaries, not one repo at a time. Big picture
before details.

## 2. Relevant Files & Components

| Repo | File | Layer | Role |
| ---- | ---- | ----- | ---- |
| backend | `app/services/measurements/...` | service | ... |
| web | `services/measurement.service.ts` | api client | ... |
| mobile | `presentation/feature/measurement/...` | presentation | ... |

Paths are repo-relative; the repo column says which checkout they live in.

## 3. Database Schema

For every table involved, the full column list with types and constraints.

### `table_name`

| Column | Type | Constraints | Notes |
| ------ | ---- | ----------- | ----- |
| `id` | int | PK | |

Also note indexes, unique constraints, foreign keys, enum types, and which Alembic revision
introduced it. Say whether this was read from `alembic/versions/`, from `app/models/`, or both.

## 4. Key Code Snippets

For each major component, the excerpt that reveals _how it works_ — not just its name.

### `FileName` (repo) — Short description

\`\`\`python
# snippet
\`\`\`

## 5. Data Flow & Architecture

### Diagram

\`\`\`mermaid
flowchart TD
  A[Mobile: MeasurementScreen] --> B[POST /api/v1/measurements]
  B --> C[MeasurementService]
  C --> D[MeasurementRepository]
  D --> E[(measurements)]
\`\`\`

Label each node with its repo when the flow crosses a boundary. Show where the centralized
auth / establishment-permission middleware sits in the chain.

### Narrative

Step-by-step trace with specific function names, route paths, and tables.

## 6. Cross-Repo Contracts

The seams this feature will have to move. For each: the endpoint, who calls it, the current
request/response shape, and which repos would have to change together if it changed.

| Contract | Producer | Consumers | Breaking to change? |
| -------- | -------- | --------- | ------------------- |

Flag anything the mobile app consumes, since old builds stay installed on real devices long
after the API moves on.

## 7. Auth & Permissions

Which roles (`admin`, `analyst`, `field_worker`) can reach this flow, and how per-establishment
access is resolved. The access token carries `user_id` and `role` only — establishment access
is a request-time DB query handled by centralized middleware, never inline in an endpoint.
Say which middleware/dependency guards the routes in scope.

## 8. Key Dependencies & Integrations

External services, packages, or internal modules this area depends on. Note anything that
could be a constraint or a risk.

## 9. Open Questions & Gaps

Things uncertain, assumptions made, or areas needing clarification before planning.

## 10. Self-Check

- Did every lane cover its assigned files? (list any skipped and why)
- Are there flows traced incompletely, or that stop at a repo boundary?
- Is the DB schema complete for every relevant table, and was model/migration drift checked?
- Are code snippets present for every major component?
- Does the Mermaid diagram match the narrative?
- Is every cross-repo contract in §6 named concretely (method + path + payload), not just "the API"?
- What is the biggest unknown that could derail the implementation plan?
```

---

## Step 5 — Self-check pass

Re-read research.md critically before finishing:

- Is any section shallow or hand-wavy?
- Does the diagram accurately reflect the narrative?
- Is the data flow specific enough to plan against?
- Does §6 actually let a planner see which repos move together?

If gaps exist, spawn a targeted follow-up agent to fill them, then update the document.

## Done

Tell the user:

```
research.md is ready at docs/plans/<N>-<feature-name>/research.md.
Repos covered: <list>.

Review it and let me know if anything looks off or if you'd like me to dig deeper
into any section before moving to planning.
```
