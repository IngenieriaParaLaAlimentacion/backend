---
name: implement-plan
description: Implement an approved technical plan phase by phase, verifying each step against the plan's automated checks (ruff, Alembic, pytest). Use this command when the user wants to implement a plan from docs/plans/, pick up where they left off, continue implementing a feature plan, or says anything like "implement the plan," "start the plan," "pick up from phase 2," or "continue the nutrir meal-planning plan."
---

# Implement Plan

Implement approved technical plans from `docs/plans/`. Plans are produced by `/create_plan` and contain phases with specific changes, automated verification commands, and success criteria.

> Project context lives in `CLAUDE.md`, `docs/architecture.md`, `docs/auth.md`, and `docs/conventions.md`. The plan must respect the layer boundaries (`api/` → `services/` → `repositories/` → `models/`) and architecture rules defined there — auth is centralized in middleware, business logic stays in `app/services/`, and schema changes only happen through Alembic migrations.

## Getting Started

When given a plan path (or when you can infer it from context):

1. Read the plan completely and check for existing checkmarks (`- [x]`)
2. Read the originating user story (`docs/user-stories/`) and all files the plan mentions
3. Read files fully — you need complete context to understand how the layers fit together
4. Start implementing if you understand what needs to be done

If no plan path is provided or inferable, ask for one.

## Implementation Flow

### Follow the plan's intent, not just its letter

Plans are carefully designed, but the codebase may have evolved since they were written. Your job is to:

- Implement each phase fully before moving to the next
- Follow the natural layer order for a new feature: model → migration → repository → service → schema → API route → tests
- Verify your work after each phase (see Verification below)
- Adapt to what you actually find in the code while preserving the plan's intent

### When things don't match

If you encounter a mismatch between the plan and reality, stop and present it clearly:

```
Issue in Phase [N]:
Expected: [what the plan says]
Found: [actual situation]
Why this matters: [explanation]

How should I proceed?
```

This matters because silently deviating from the plan leads to subtle bugs and confused reviews.

## Verification

Each plan defines its own automated checks under **Success Criteria → Automated Verification**. After completing a phase, run that phase's checks. When the plan doesn't list specific commands, fall back to the project defaults below — run only the ones relevant to what the phase changed:

```bash
# Lint and format (always) — this is exactly what CI's pre-commit step runs:
# the hooks pinned in .pre-commit-config.yaml, which FAIL if a hook rewrites a file.
poetry run pre-commit run --all-files
# Faster inner-loop while iterating (NOT a substitute for the pre-commit check above):
#   poetry run ruff check . && poetry run ruff format --check .

# Migrations (only if the phase changed models/schema)
poetry run alembic upgrade head
poetry run alembic downgrade -1 && poetry run alembic upgrade head   # round-trip check

# Tests
poetry run pytest tests/unit/          # fast, no Docker
poetry run pytest                      # full suite — requires Docker (Testcontainers)
poetry run pytest --cov=app            # confirm coverage holds
```

Notes specific to this project:

- There is no compile step — Python is interpreted. "Verification" means lint, migrations, and tests pass, not a build.
- The full test suite needs Docker running (Testcontainers spins up PostgreSQL). If Docker isn't available, run `poetry run pytest tests/unit/` and say so explicitly rather than claiming the full suite passed.
- After generating an Alembic migration with `--autogenerate`, always open the file in `alembic/versions/` and review it — autogenerate misses some changes.
- CI's lint gate is the **pre-commit** step (`pre-commit/action` in `.github/workflows/ci.yml`), which runs the hooks pinned in `.pre-commit-config.yaml` and **fails if any hook modifies a file** — not only on errors. So `poetry run pre-commit run --all-files` is the source of truth for lint/format, not a bare `ruff check`: a loose `ruff check` can pass while CI fails (e.g. a file `ruff-format` would rewrite, or a different pinned ruff version). Run pre-commit before claiming a phase is verified. First run downloads the pinned hook env (needs network); it's cached afterward.

Fix any issues before moving to the next phase.

### Update progress as you go

Check off completed items in the plan file itself using Edit. This lets you and the user track exactly where things stand, and makes it easy to resume if interrupted.

## Resuming Work

If the plan has existing checkmarks:

- Trust that completed work is done
- Pick up from the first unchecked item
- Verify previous work only if something seems off during your implementation

## If You Get Stuck

When something isn't working as expected:

1. Read and understand all the relevant code — most issues come from incomplete context
2. Consider if the codebase has evolved since the plan was written
3. Present the mismatch clearly and ask for guidance

Use sub-agents sparingly — mainly for targeted investigation of unfamiliar areas of the codebase (`Explore` for read-only fan-out searches across `app/models/`, `app/repositories/`, `app/services/`, `app/api/`).

## Keep momentum

You're implementing a solution, not just checking boxes. Batch verification at natural stopping points (end of a phase); don't let it interrupt your flow within a phase.
