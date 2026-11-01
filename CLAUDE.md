# CLAUDE.md

## What this service is

REST API for the integral nutritional management and food security platform aimed at community kitchens, health teams, and social organizations in Argentina.

The backend is the sole orchestrator of LLM calls, image processing, and external storage. Mobile app and backoffice web clients consume this REST API — they never call external services directly.

## Stack

| Layer | Technology |
|---|---|
| Language | Python 3.11+ |
| Framework | FastAPI |
| ORM | SQLAlchemy (async) |
| DB Driver | asyncpg |
| Database | PostgreSQL |
| Migrations | Alembic |
| Rate limiting | Redis (falls back to in-memory counters) |
| LLM | OpenRouter |
| Object storage | Cloudflare R2 (S3-compatible) |
| Dependencies | Poetry 2.0 |
| Linting/format | Ruff |
| Tests | pytest + Testcontainers |
| Deploy | Docker on Railway |

## Functional modules

| Module | Code modules | Description |
|---|---|---|
| `talla_y_peso` | `subjects`, `measurements` | Subjects and height/weight registration with georeferencing per establishment |
| `encuesta_alimentaria` | `surveys` | Configurable surveys, includes FAO FIES instrument |
| `nutrir` | `food_catalog`, `food_intakes`, `food_outflows`, `food_stock`, `recipes` | Food catalog and stock movements, AI-assisted recipe proposals |
| `dashboard` | analytics routes and services | Cross-module analytics panel for technical profiles |
| `auth` | `auth`, `establishments` | Users, roles, and per-establishment permissions |

`nutrition_reports` (monthly report PDF) and `notifications` (push) are also code modules.

## Project structure

```
app/
  main.py                     # FastAPI app entry point
  api/                        # Route handlers, grouped by API version
  services/<module>/          # Business logic, one subdir per module
  repositories/<module>/      # DB access layer, one subdir per module
  models/<module>/            # SQLAlchemy ORM models
  schemas/<module>/           # Pydantic request and response models
  domain/                     # Enums and plain domain types
  core/                       # Ports (core/interfaces), dependencies, security, rate limiting
  config/settings.py          # Settings (pydantic-settings, loaded from .env)
  db/                         # Async engine, session factory, unit of work
  exceptions/                 # Domain exceptions and their HTTP handlers
  reference_data/             # Reference datasets and seeding helpers
alembic/
  versions/                   # Migration files
tests/
  unit/, integration/, load/  # Integration tests need Docker (Testcontainers)
```

## Quick commands

```bash
poetry run uvicorn app.main:app --reload    # dev server
poetry run pytest                           # tests (integration needs Docker)
poetry run pytest tests/unit                # unit tests only
poetry run alembic upgrade head             # apply migrations
poetry run ruff check . --fix && poetry run ruff format .  # lint + format
```

→ Full setup, Docker, and migration commands: `docs/commands.md`

## Architecture rules

- Establishment permission checks go through `app/services/access.py::check_establishment_access` — never re-derive the rule inline in a route handler.
- Business logic belongs in `app/services/`, not in route handlers or repositories.
- Route handlers live in `app/api/` and are mounted in `app/main.py` — never add routes directly to `main.py`.
- Never modify the DB schema manually — all changes go through Alembic migrations.

→ Full architecture details: `docs/architecture.md`

## Auth and authorization

- Access token contains `user_id` and `role`. Per-establishment access is **not** in the token — resolved at request time via DB query.
- Establishment permission checks live in one shared service helper, `app/services/access.py::check_establishment_access` — services call it explicitly; **never re-implement the rule inline**.
- Roles: `superadmin`, `admin`, `analyst`, `field_worker`.

→ Full auth model, token flow, and data model: `docs/auth.md`

## Conventions

- **Commits**: Conventional Commits — `feat:`, `fix:`, `chore:`, `docs:`, `test:`, `refactor:`, `ci:`.
- **Branches**: `develop` (integration) and `main` (release). Work on `feat/`, `feature/`, `fix/`, `refactor/`, `docs/` or `chore/` branches and open PRs into `develop`; CI enforces this.
- **Language**: English for all code, comments, and documentation.
- **Docstrings**: describe *what* the code does, never why it was built that way. Rationale belongs in an inline `#` comment on the line it guards.
- **Format**: Ruff, double quotes, line length 88. Pre-commit hooks run automatically.

→ Full conventions (naming, layers, docstrings, PRs): `docs/conventions.md` and `CONTRIBUTING.md`

## Documentation

Project documentation lives in `docs/`. Keep temporary plans and reviews in the git-ignored `docs/plans/` and `docs/reviews/`.

| Document | Read it when |
|---|---|
| `docs/commands.md` | Setting up, running, migrating, Docker, E2E data |
| `docs/architecture.md` | Changing layers, modules, integrations, deployment |
| `docs/auth.md` | Touching tokens, roles, rate limiting, establishment access |
| `docs/api.md` | Adding or changing endpoints (general API conventions) |
| `docs/errors.md` | Looking up an error type. Generated: after changing errors run `poetry run python docs/generate_error_catalog.py` (a unit test checks it) |
| `docs/adr/` | Understanding why a design decision was made. Number new ADRs sequentially, without repeating numbers |
| `docs/csv-exports.md`, `docs/subjects-offline-sync.md` | Guides for the web and mobile clients: consuming the CSV exports, and offline-first subject sync |
| `CONTRIBUTING.md` | Branches, commits, PR rules, CI |

When you add, rename, or remove a document under `docs/`, update this table and the documentation list in the READMEs.
