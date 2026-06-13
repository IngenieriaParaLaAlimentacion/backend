# Implementation Plan

Use this command before implementing any feature, refactor, or migration that touches more than one file or crosses layers (`api/` → `services/` → `repositories/` → `models/`). For single-file changes, a lightweight approach (quick summary + go) is fine — reserve this full process for multi-file, multi-phase work.

Create detailed implementation plans through an interactive, iterative process. Be skeptical, thorough, and work collaboratively with the user to produce high-quality technical specifications grounded in this codebase's conventions.

> Project context lives in `CLAUDE.md`, `docs/architecture.md`, `docs/auth.md`, and `docs/conventions.md`. Read the relevant ones before planning — they define the layer boundaries and architecture rules every plan must respect.

## Initial Response

When this command is invoked:

1. **Check if parameters were provided**:
    - If a file path or ticket reference was provided as a parameter, skip the default message
    - Immediately read any provided files FULLY
    - Begin the research process

2. **If no parameters provided**, respond with:

```
I'll help you create a detailed implementation plan. Let me start by understanding what we're building.

Please provide:
1. The task/ticket description (or a reference, e.g. AUTH-12, or a path to a spec file)
2. The module(s) involved (talla_y_peso, encuesta_alimentaria, valores_de_hierro, nutrir, dashboard, auth) or "new module"
3. Any relevant context, constraints, or specific requirements
4. Links to related research or previous implementations

I'll analyze this against the codebase and work with you to create a comprehensive plan.

Tip: You can also invoke this command with a spec file directly: `/create_plan docs/specs/nutrir_meal_endpoint.md`
For deeper analysis, try: `/create_plan think deeply about AUTH-12`
```

Then wait for the user's input.

## Process Steps

### Step 1: Context Gathering & Initial Analysis

1. **Read all mentioned files completely** (specs, research docs, existing plans, JSON) using the Read tool without limit/offset. Read them in the main context before spawning any sub-tasks — sub-tasks lack conversational context, so you need to understand the material first to decompose research effectively.

2. **Read the relevant project docs** for any plan: `docs/conventions.md` (layer separation, naming), `docs/architecture.md`, and `docs/auth.md` when the change touches authentication or per-establishment permissions.

3. **Spawn research sub-agents in parallel** before asking the user any questions. Use the Agent tool:
    - `Explore` — read-only fan-out search to locate every file related to the task (models, repositories, services, api routes, schemas, migrations, tests for the affected module). Specify breadth ("very thorough" for new features spanning layers).
    - `general-purpose` — for multi-step investigation of how an existing implementation works, when locating is not enough and you need the call flow traced across layers.
    - Use a second `Explore` to find a similar existing module to model after (e.g. study `talla_y_peso` when planning a new measurement-style module).

4. **Read all files identified by research tasks** into the main context after they complete, so you have complete understanding before proceeding.

5. **Analyze and verify understanding**:
    - Cross-reference the requirements with actual code
    - Identify any discrepancies or misunderstandings
    - Note assumptions that need verification
    - Confirm which layers are affected and whether a DB schema change (Alembic migration) is needed
    - Check whether auth/permission behavior is involved — remember it is centralized in middleware, never per-endpoint
    - Determine true scope based on codebase reality

6. **Present informed understanding and focused questions**:

    ```
    Based on the task and my research of the codebase, I understand we need to [accurate summary].

    I've found that:
    - [Current implementation detail with file:line reference]
    - [Relevant pattern or layer convention discovered]
    - [Potential complexity, migration need, or edge case identified]

    Questions that my research couldn't answer:
    - [Specific technical question that requires human judgment]
    - [Business/domain logic clarification]
    - [Design preference that affects implementation]
    ```

    Only ask questions that you genuinely cannot answer through code investigation.

### Step 2: Research & Discovery

After getting initial clarifications:

1. **If the user corrects any misunderstanding**, don't just accept it — spawn new research to verify the correct information against the actual codebase before proceeding.

2. **Spawn parallel sub-agents for comprehensive research** using the Agent tool:
    - `Explore` — locate specific files for each layer the task touches (`app/models/<module>/`, `app/repositories/<module>/`, `app/services/<module>/`, `app/api/v1/`, `app/schemas/`, `alembic/versions/`, `tests/`)
    - `general-purpose` — trace implementation details and data flow of relevant components across layers
    - A focused `Explore` — find a similar feature elsewhere in the codebase to model the new work after
    - `Plan` — when an architectural trade-off needs a designed option set (returns step-by-step plans and identifies critical files)

    Launch multiple agents in parallel for efficiency. Each should return specific `file:line` references.

3. **Wait for ALL sub-agents to complete** before proceeding.

4. **Present findings and design options**:

    ```
    Based on my research, here's what I found:

    **Current State:**
    - [Key discovery about existing code, with file:line]
    - [Layer convention or pattern to follow]

    **Design Options:**
    1. [Option A] - [pros/cons]
    2. [Option B] - [pros/cons]

    **Open Questions:**
    - [Technical uncertainty]
    - [Design decision needed]

    Which approach aligns best with your vision?
    ```

### Step 3: Plan Structure Development

Once aligned on approach:

1. **Create initial plan outline**. Phase the work along the layer boundaries when it's a new feature — the natural order in this codebase is model → migration → repository → service → schema → API route → tests:

    ```
    Here's my proposed plan structure:

    ## Overview
    [1-2 sentence summary]

    ## Implementation Phases:
    1. [Phase name] - [what it accomplishes]
    2. [Phase name] - [what it accomplishes]
    3. [Phase name] - [what it accomplishes]

    Does this phasing make sense? Should I adjust the order or granularity?
    ```

2. **Get feedback on structure** before writing details

### Step 4: Detailed Plan Writing

After structure approval:

1. **Write the plan** to `docs/plans/{descriptive_name}.md`
2. **Use this template structure**:

````markdown
# [Feature/Task Name] Implementation Plan

## Overview

[Brief description of what we're implementing and why]

## Current State Analysis

[What exists now, what's missing, key constraints discovered — with file:line references]

## Desired End State

[A specification of the desired end state after this plan is complete, and how to verify it]

### Key Discoveries:

- [Important finding with file:line reference]
- [Layer convention or pattern to follow]
- [Constraint to work within — e.g. auth is centralized in middleware, schema changes only via Alembic]

## What We're NOT Doing

[Explicitly list out-of-scope items to prevent scope creep]

## Implementation Approach

[High-level strategy and reasoning. Note which layers are touched and whether a migration is required.]

## Phase 1: [Descriptive Name]

### Overview

[What this phase accomplishes]

### Changes Required:

#### 1. [Component/File Group — e.g. Model, Migration, Repository, Service, Schema, Route]

**File**: `app/<layer>/<module>/<file>.py`
**Changes**: [Summary of changes]

```python
# Specific code to add/modify
```

### Success Criteria:

#### Automated Verification:

- [ ] Lint + format pass exactly as CI does (pinned hooks, fails if any hook rewrites a file): `poetry run pre-commit run --all-files`
- [ ] Migration applies cleanly (if schema changed): `poetry run alembic upgrade head`
- [ ] Migration round-trips (if schema changed): `poetry run alembic downgrade -1 && poetry run alembic upgrade head`
- [ ] Unit tests pass: `poetry run pytest tests/unit/`
- [ ] Full suite passes (requires Docker for Testcontainers): `poetry run pytest`
- [ ] Coverage holds: `poetry run pytest --cov=app`

#### Manual Verification:

- [ ] Endpoint behaves as expected via the OpenAPI docs at `http://0.0.0.0:8080/docs` (or `curl`)
- [ ] Per-establishment permission checks behave correctly (allowed/denied) — handled by middleware, not the endpoint
- [ ] Response uses the standard error/response shape and error messages are user-friendly
- [ ] DB state is correct after the operation
- [ ] No regressions in related endpoints

---

## Phase 2: [Descriptive Name]

[Similar structure with both automated and manual success criteria...]

---

## Testing Strategy

### Unit Tests:

- [What to cover in `tests/unit/` — services and repositories in isolation]

### Integration Tests:

- [Endpoint/DB behavior covered via Testcontainers — note Docker is required]

### Manual Testing Steps:

1. [Specific step to verify the feature via /docs or curl]
2. [Auth/permission scenario to verify]
3. [Edge case to test manually]

## Performance Considerations

[Any performance implications — e.g. N+1 queries, missing pagination/LIMIT, indexes needed on new columns]

## Migration Notes

[If a schema change is involved: the Alembic revision, data backfill needs, and rollback (`alembic downgrade -1`) behavior]

## References

- Ticket: `AUTH-12` (or external tracker reference)
- Related spec/research: `docs/[relevant].md`
- Similar implementation: `app/services/<module>/[file].py:line`
- Conventions: `docs/conventions.md`, `docs/architecture.md`, `docs/auth.md`
````

### Step 5: Review

1. **Present the draft plan location**:

    ```
    I've created the initial implementation plan at:
    `docs/plans/[filename].md`

    Please review it and let me know:
    - Are the phases properly scoped along the layer boundaries?
    - Are the success criteria specific enough?
    - Any technical details that need adjustment?
    - Missing edge cases, auth scenarios, or migration considerations?
    ```

2. **Iterate based on feedback** - be ready to:
    - Add missing phases
    - Adjust technical approach
    - Clarify success criteria (both automated and manual)
    - Add/remove scope items

3. **Continue refining** until the user is satisfied

## Important Guidelines

1. **Be Skeptical**:
    - Question vague requirements
    - Identify potential issues early
    - Ask "why" and "what about"
    - Don't assume — verify with code

2. **Be Interactive**:
    - Don't write the full plan in one shot
    - Get buy-in at each major step
    - Allow course corrections
    - Work collaboratively

3. **Be Thorough**:
    - Research actual code patterns using parallel sub-agents
    - Include specific file paths and line numbers
    - Write measurable success criteria with a clear automated vs manual distinction

4. **Be Practical**:
    - Focus on incremental, testable changes
    - Consider migration and rollback (`alembic downgrade -1`)
    - Think about edge cases
    - Include "what we're NOT doing"

5. **Respect the architecture** (from `CLAUDE.md` and `docs/conventions.md`):
    - Business logic belongs in `app/services/` — never in route handlers or repositories
    - Route handlers live in `app/api/` and are mounted via routers — never add routes directly to `app/main.py`
    - Repositories do DB queries only; services never touch the DB directly or know about HTTP
    - Auth/per-establishment permission checks are centralized in middleware — never check them inline per endpoint
    - Never modify the DB schema manually — all schema changes go through Alembic migrations
    - All code, comments, and docstrings in English; Ruff formatting (double quotes, line length 88)

6. **Track Progress**:
    - Use TaskCreate to track planning tasks
    - Update tasks as you complete research
    - Mark planning tasks complete when done

7. **No Open Questions in Final Plan**:
    - If you encounter open questions during planning, STOP
    - Research or ask for clarification immediately
    - Do NOT write the plan with unresolved questions
    - The implementation plan must be complete and actionable
    - Every decision must be made before finalizing the plan

## Success Criteria Guidelines

**Always separate success criteria into two categories:**

1. **Automated Verification** (can be run by execution agents):
    - `poetry run pre-commit run --all-files` — the lint/format source of truth; runs the hooks pinned in `.pre-commit-config.yaml`, exactly as CI does, and fails if any hook rewrites a file. (A bare `poetry run ruff check .` is fine as a faster inner-loop check but can pass while CI fails.)
    - `poetry run alembic upgrade head` (and a downgrade round-trip when schema changed)
    - `poetry run pytest` / `poetry run pytest tests/unit/` / `poetry run pytest --cov=app`
    - Specific files that should exist (new model, migration, repository, service, route)

2. **Manual Verification** (requires human testing):
    - Endpoint behavior via the OpenAPI docs (`/docs`) or `curl`
    - Auth and per-establishment permission scenarios
    - Performance under realistic data
    - Edge cases that are hard to automate
    - User-friendly error responses

**Format example:**

```markdown
### Success Criteria:

#### Automated Verification:

- [ ] Lint + format pass exactly as CI does: `poetry run pre-commit run --all-files`
- [ ] Migration applies: `poetry run alembic upgrade head`
- [ ] Unit tests pass: `poetry run pytest tests/unit/`
- [ ] Full suite passes (Docker required): `poetry run pytest`

#### Manual Verification:

- [ ] New endpoint returns the expected payload via /docs
- [ ] establishment_manager is denied access to other establishments' data
- [ ] Error messages are user-friendly and use the standard response shape
- [ ] No regressions in related endpoints
```

## Common Patterns

### For Database / Schema Changes:

- Update or add the ORM model in `app/models/<module>/`
- Generate the migration: `poetry run alembic revision --autogenerate -m "short description"`, then review the generated file in `alembic/versions/`
- Add/adjust repository methods in `app/repositories/<module>/`
- Update business logic in `app/services/<module>/`
- Update Pydantic schemas in `app/schemas/`
- Expose via the API route in `app/api/v1/` (mounted through a router)

### For New Features:

- Research existing module patterns first (study a similar module like `talla_y_peso`)
- Start with the data model (`app/models/<module>/`) and migration
- Build the repository layer (DB queries only)
- Build the service layer (business/domain logic)
- Define request/response schemas (`app/schemas/`)
- Add API endpoints (`app/api/v1/`) and mount the router — never edit `app/main.py` routes directly
- Add unit tests (`tests/unit/`) and integration coverage

### For Refactoring:

- Document current behavior
- Plan incremental changes that keep layer boundaries intact
- Maintain backwards compatibility (API contracts, DB)
- Include a migration strategy and rollback path when schema is involved

## Sub-agent Best Practices

When spawning research sub-agents via the Agent tool:

1. **Launch multiple agents in parallel** in a single message for efficiency
2. **Each agent should be focused** on a specific area/layer with a clear prompt
3. **Include full path context** in prompts (e.g. `app/services/nutrir/`, `alembic/versions/`) so agents search the right directories
4. **Request specific `file:line` references** in agent responses
5. **Wait for all agents to complete** before synthesizing findings
6. **Verify results** — if an agent returns unexpected results, spawn follow-ups or cross-check against the codebase yourself
7. **Pick the right agent**: `Explore` for read-only fan-out location, `general-purpose` for multi-step investigation, `Plan` for designing implementation options

## Example Interaction Flow

```
User: /create_plan
Assistant: I'll help you create a detailed implementation plan...

User: We need to add a hemoglobin-trend endpoint to the valores_de_hierro module. See AUTH-12 / docs/specs/iron_trend.md
Assistant: Let me read that spec file completely first...

[Reads file fully, reads docs/conventions.md and docs/auth.md]

[Spawns Explore agents in parallel to locate the valores_de_hierro model, repository, service, and routes]

Based on the spec and my research, I understand we need to expose a hemoglobin trend over time for a subject, reading from the existing valores_de_hierro tables. The service layer already has [X] at app/services/valores_de_hierro/...:line. Before I start planning, I have some questions...

[Interactive process continues...]
```
