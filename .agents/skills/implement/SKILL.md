---
name: implement
description: >
  Phase 3 of the feature development workflow. Use this skill whenever the user invokes /implement
  or asks to implement, build, code, or execute a plan produced by /plan (Phase 2).
  Triggers on: "/implement [folder]", "implement this plan", "build this feature", "phase 3",
  "let's implement", "code this up", "execute the plan", "start building", "let's build it".
  Reads the plan.md from Phase 2, uses the dedicated worktree assigned to each Ingeniería para
  la Alimentación repo (backend, backoffice, app_mobile), creates client branches, spawns parallel agents per lane, runs
  each repo's tests/lint/typecheck, cleans the code, and opens one PR per repo in the plan's
  landing order. Use this skill even if the user just says "let's build" or "implement it".
---

# Implement Skill — Phase 3

You are performing Phase 3 of a structured feature-development workflow. Your job is to turn
a plan.md into working, tested, linted code across every repo the feature touches — then open
one PR per repo, in the order the plan specifies.

## The repos and feature worktrees

```bash
bash .agents/scripts/feature-worktrees.sh require <N>-<feature-name> backend web mobile
bash .agents/scripts/feature-worktrees.sh list <N>-<feature-name>
```

`backend` is the current Conductor worktree; `web` and `mobile` are the dedicated worktrees
created during research. Every git and build command below runs with `-C <recorded-path>` or
from inside that path. Never fall back to the repositories' main checkouts.

## Input

```
/implement <N>-<feature-name>
```

If the folder argument is missing, list the numbered `docs/plans/` directories and ask which to
implement. If `docs/plans/<N>-<feature-name>/plan.md` does not exist, tell the user to run
`/plan` first.

## Step 1 — Read the plan

Read `docs/plans/<N>-<feature-name>/plan.md` in full. Extract:

- **§4 PR Plan & Landing Order** — which repos, which branches, in what order, and what makes
  each PR safe alone
- **§5 Tasks Checklist** — your ordered work items
- **§3 Architecture Diagram** — goes in the PR bodies
- **§11 Validation** — the commands you must make pass
- A ticket reference if the plan carries one (optional — this workflow does not require one)

Read `AGENTS.md` when present and the conventions it points to in every repo in scope. In particular, read
the backend's `CLAUDE.md`, `docs/conventions.md`, `docs/architecture.md`, and `docs/auth.md`;
the mobile app's `CLAUDE.md`; and the web app's `CLAUDE.md`, `docs/architecture.md`, and
`docs/conventions.md`.

Require the full feature worktree set before implementation, even when the plan changes only a
subset of repos. A missing or invalid recorded worktree fails now rather than halfway through.

## Step 2 — Establish one feature branch per repo

Preserve the backend's existing task branch — Conductor owns its name. Use the branch names
recorded in the plan for the clients, preferably the same name in both repos. The client
worktrees begin detached at `origin/develop`; after confirming each is clean, create the
planned branch in place:

```bash
git -C <repo-path> checkout -b <type>/<feature-name> origin/develop
```

**Base every branch on `develop`** — all three repos use `develop` for feature PRs and reserve
`main` for release promotion. The branch prefix must be one of `feat/`, `fix/`, `refactor/`,
`docs/` or `chore/`: the backoffice enforces this in CI (`pr-branch-policy.yaml`) and rejects
anything else targeting `develop`.

The backend is the worktree you are already standing in. Never rename or switch its branch from
inside Conductor.

Before branching a client repo, check it is clean (`git -C <path> status --porcelain`). On a
resumed run, continue when it is already on the branch named by the plan. If it is on any other
branch, stop and report the mismatch rather than switching, stashing, or deleting work.

## Step 3 — Implement with parallel lane agents

Spawn one agent per lane that has tasks, in the same turn. Lanes match the plan's:
`api-data`, `api-backend`, `web`, `mobile`, `cross-cutting`.

Respect dependencies: if `api-backend` needs the models `api-data` creates, spawn the other
lanes first and give `api-backend` the finished output as context. Most plans avoid this
because Phase 2 already fixed the interfaces.

Agent prompt template:

```
You are implementing part of the "<feature-name>" feature.
You are a Senior Software Engineer. Write production-quality code that follows the
project's existing conventions.

## Your repo
<repo-key> at <absolute path>. Work only inside that path.
Branch: <branch-name> (already created and checked out)

## Your tasks
<the specific checklist items assigned to this lane>

## Implementation specs
<the relevant plan.md sections for this lane>

## Project conventions
<the repo's conventions file content — for the backend, docs/conventions.md and
docs/architecture.md too>

## Hard rules for your lane
- backend: layers do not leak. Routes parse and delegate; services hold the business
  logic and never touch the DB; repositories only query; models only declare. Routes are
  mounted through app/api/router.py, never in app/main.py. Establishment permission
  checks stay in the centralized middleware — never inline in an endpoint.
- backend: all code, comments and docstrings in English. Public classes and methods get a
  docstring. Ruff formatting: double quotes, 88 columns.
- mobile: CLEAN + MVVM. New screens use the six-file pattern (Action / Destination /
  Navigation / Screen / State / ViewModel), register the route in Route.kt, wire it into
  AppNavHost.kt, and bind dependencies in the Koin module. Colors and type come from
  AlTheme; icons are MingCute vector drawables loaded with vectorResource — never
  androidx.compose.material.icons.*.
- web: reuse components/ui shadcn primitives, fetch through a services/*.service.ts call
  wrapped in a hooks/use*.ts swr hook, validate forms with a zod schema in schemas/.

## Instructions
1. Read the existing files you need to modify before changing them
2. NEW files: create them with the full implementation from the plan
3. MODIFIED files: apply the BEFORE/AFTER diffs from the plan
4. Follow the existing style in each file (indentation, naming, imports)
5. Write tests for new logic:
   - Backend: tests/unit/ for services and pure logic, tests/integration/ for a new
     endpoint or repository query
   - Mobile: commonTest / androidUnitTest where the repo already has coverage
   - Web: co-located *.test.tsx only where the repo already has tests
6. Do NOT run migrations. Write the Alembic revision file, but do not run
   `alembic upgrade` against any database and do not use --autogenerate against a live DB.
7. Do NOT commit — the parent handles commits.

If the plan does not match what you find in the code, STOP and report the mismatch
instead of improvising. Say what the plan expected, what is actually there, and why
it matters.

Do NOT skip any task assigned to you.
```

**If an agent reports a mismatch**, do not paper over it. Present it and let the user choose:

```
Issue in <lane>:
Expected: <what the plan says>
Found: <actual situation>
Why this matters: <explanation>
```

Ask the user whether to adapt, follow the plan as written, or stop and revise the plan; put the
recommended option first. A plan written against a moving codebase goes stale; several agents
implementing a stale plan in parallel is the failure this check exists to prevent.

Tick off `§5` items in plan.md as they land, so an interrupted run can resume from the first
unchecked box.

## Step 4 — Commit per repo, per layer

Commit inside each repo in dependency order (`api-data` → `api-backend` → clients):

```bash
git -C <repo-path> add <paths>
git -C <repo-path> commit -m "<type>(<scope>): <description>"
```

Conventional commits (`feat`, `fix`, `chore`, `docs`, `test`, `refactor`), matching what each
repo already uses (`git -C <path> log --oneline -10` if unsure). Prefix with a ticket id only
if the plan carries one. **No agent attribution or Co-Authored-By lines in commits.**

The backend runs Ruff through pre-commit hooks, so a commit is blocked if a hook rewrites a
file. Re-stage the rewritten file and commit again — never bypass the hooks.

## Step 5 — Quality checks, per repo

Run each repo's real commands. Fix what fails, then re-run — do not disable rules.

| Repo | Commands |
| ---- | -------- |
| backend | `poetry run pre-commit run --all-files`, `poetry run pytest tests/unit/`, `poetry run pytest` (full suite, needs Docker) |
| web | `npm run lint`, `npm run typecheck`, `npm run build` |
| mobile | `./scripts/compile.sh`, `./gradlew :composeApp:testDebugUnitTest` |

Backend local-environment notes: Poetry may not be on PATH
(`/Users/juanduzac/.local/bin/poetry`) and an unrelated venv is often active, so run it as
`env -u VIRTUAL_ENV poetry …`. Each worktree has its own venv, empty until you run
`env -u VIRTUAL_ENV poetry install --no-root` there. Integration tests need Docker running
(`open -a Docker`, then wait for `docker info`); `tests/unit/` does not. CI's lint gate is
pre-commit, not bare `ruff check`, so a green `ruff check .` can still fail CI.

If Docker is unavailable, run `tests/unit/` and say plainly in the report that the integration
suite was not run.

Commit fixes separately: `fix(<scope>): resolve lint/type/test issues`.

## Step 6 — Clean the code

Run the cleanup passes over each repo's diff, in this order — it is not arbitrary. `/simplify`
reshapes structure first, and `/code-review` runs **last** so it reads the code that will
actually be reviewed.

1. `/simplify` — reuse, simplification, efficiency, altitude; it also strips AI narration
   comments and unjustified abstractions
2. `/code-review` — correctness bugs
3. `/review` (this repo's own skill) for the backend diff — layer discipline, naming and
   guardrail violations specific to this codebase

Point each at the diff of the repo you are cleaning. Triage every finding: fix real bugs and
clear wins, skip false positives with a one-line reason. Re-run the Step 5 checks for anything
you touched.

Commit per repo: `refactor(<scope>): simplify`, then `chore(<scope>): address review findings`.

## Step 7 — Confirm before opening PRs

```
Implementation is complete. Here's what was done:

**backend** — branch `<name>`, <n> commits, pre-commit/tests clean
  created: <files>
  modified: <files>
**web** — branch `<name>`, <n> commits, lint/typecheck/build clean
  ...

**Landing order:** backend → web → mobile

Ready to open the PRs? Any changes you'd like first?
```

Wait for confirmation.

## Step 8 — Push and open one PR per repo

Push and open in the plan's landing order. Before opening, check the branch does not already
have an open PR (`gh pr view --json number,url,state`) — reuse it if so rather than opening a
second.

```bash
git -C <repo-path> push -u origin <branch-name>
gh pr create --repo IngenieriaParaLaAlimentacion/<backend|backoffice|app_mobile> \
  --base develop \
  --title "<type>(<scope>): <short description>" \
  --body-file <body-file>
```

PR body:

```markdown
## Summary

<1-3 bullets on what this PR does>

## Architecture

<the Mermaid diagram from plan.md §3 — so reviewers see the interactions at a glance>

## Changes

- <list>

## Related PRs

Part of <feature-name>. Lands after <repo/PR> and before <repo/PR>.
Safe to merge on its own because <reason from plan §4>.

## Test Plan

- [ ] <the repo's commands from plan §11>
- [ ] <feature-specific manual steps>

```

Only open a client PR once the API PR it depends on is open, and say plainly in the client PR
that it needs the API deployed — and its migration applied — first.

## Step 9 — Report

```
PRs opened:
- backend: <url>
- web:     <url>
- mobile:  <url>

Merge order: backend → web → mobile. The backend PR needs to deploy, and its Alembic
revision to be applied, before the client PRs merge.
```
