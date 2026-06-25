# CLAUDE.md

## What this service is

REST API for the integral nutritional management and food security platform aimed at community kitchens, health teams, and social organizations in Argentina.

The backend is the sole orchestrator of LLM calls, image/audio processing, and external storage. Mobile app and backoffice web clients consume this REST API — they never call external services directly.

## Stack

| Layer | Technology |
|---|---|
| Language | Python 3.11+ |
| Framework | FastAPI |
| ORM | SQLAlchemy (async) |
| DB Driver | asyncpg |
| Database | PostgreSQL |
| Migrations | Alembic |
| Dependencies | Poetry 2.0 |
| Linting/format | Ruff |
| Tests | pytest + Testcontainers |

## Functional modules

| Module | Description |
|---|---|
| `talla_y_peso` | Height/weight registration with georeferencing per establishment (Module 1) |
| `encuesta_alimentaria` | Configurable surveys, includes FAO FIES instrument (Module 2) |
| `valores_de_hierro` | Blood hemoglobin recording with WHO alerts and informed consent (Module 3) |
| `nutrir` | AI-assisted meal planning based on available ingredients and household needs (Module 4) |
| `dashboard` | Cross-module analytics panel for technical profiles |
| `auth` | Users, roles, and per-establishment permissions |

## Project structure

```
app/
  main.py                     # FastAPI app entry point
  core/config.py              # Settings (pydantic-settings, loaded from .env)
  db/database.py              # Async SQLAlchemy engine and session factory
  models/<module>/            # SQLAlchemy ORM models, one subdir per module
  repositories/<module>/      # DB access layer, one subdir per module
  services/<module>/          # Business logic, one subdir per module
  api/<module>/               # Route handlers, one subdir per module
alembic/
  versions/                   # Migration files
tests/
  conftest.py                 # Testcontainers fixtures (requires Docker)
  unit/
```

## Quick commands

```bash
poetry run uvicorn app.main:app --reload    # dev server
poetry run pytest                           # tests (requires Docker)
poetry run alembic upgrade head             # apply migrations
poetry run ruff check . --fix && poetry run ruff format .  # lint + format
```

→ Full setup, Docker, and migration commands: `docs/commands.md`

## Architecture rules

- Auth middleware is centralized — never check establishment permissions inside individual endpoints.
- Business logic belongs in `app/services/`, not in route handlers or repositories.
- Route handlers live in `app/api/` and are mounted in `app/main.py` — never add routes directly to `main.py`.
- Never modify the DB schema manually — all changes go through Alembic migrations.

→ Full architecture details: `docs/architecture.md`

## Auth and authorization

- Access token contains `user_id` and `role`. Per-establishment access is **not** in the token — resolved at request time via DB query.
- A centralized middleware handles establishment permission checks — **never implement inline per endpoint**.
- Roles: `admin`, `analyst`, `field_workers`.

→ Full auth model, token flow, and data model: `docs/auth.md`

## Conventions

- **Commits**: Conventional Commits — `feat:`, `fix:`, `chore:`, `docs:`, `test:`.
- **Branches**: `main` (production), `feature/<ticket>` (development).
- **Language**: English for all code, comments, and documentation.
- **Format**: Ruff, double quotes, line length 88. Pre-commit hooks run automatically.

→ Full conventions (naming, layers, docstrings, PRs): `docs/conventions.md`
