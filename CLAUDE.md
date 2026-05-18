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

## Common commands

```bash
poetry install                                         # install dependencies
poetry run uvicorn app.main:app --reload               # dev server (0.0.0.0:8080)
poetry run pytest                                      # run tests (requires Docker)
poetry run alembic upgrade head                        # apply migrations
poetry run alembic revision --autogenerate -m "msg"    # generate migration
poetry run ruff check . && poetry run ruff format .    # lint and format
```

## Environment variables

Loaded from `.env` at project root (see `app/core/config.py`). All have defaults for local dev.

| Variable | Default | Notes |
|---|---|---|
| `DATABASE_HOST` | `localhost` | |
| `DATABASE_PORT` | `5432` | |
| `DATABASE_NAME` | `db` | |
| `DATABASE_USER` | `admin` | |
| `DATABASE_PASSWORD` | `password` | |
| `DATABASE_URL` | — | Overrides individual DB vars if set |
| `PORT` | `8080` | |
| `ENVIRONMENT` | `development` | |
| `JWT_SECRET` | — | Required; set to any string in tests |

## Auth and authorization

**Authentication**: custom JWT. The access token contains `user_id` and `role`. No external auth services.

**Per-establishment authorization**: establishment access is resolved at the endpoint level by querying the DB — it is not encoded in the token. A centralized middleware handles this check — **never implement it inline per endpoint**.

**Roles**: `admin`, `professional`, `establishment_manager`. Establishment managers can only load and view data for the establishments they have been assigned to.

## Architecture rules

- Auth middleware is centralized — never check establishment permissions inside individual endpoints.
- Business logic belongs in `app/services/`, not in route handlers or repositories.
- Route handlers live in `app/api/` and are mounted in `app/main.py` — never add routes directly to `main.py`.

## Sensitive data

The system stores health data of minors. Comply with Ley 25.326:
- Encrypt sensitive data at rest.
- Do not log PII (personally identifiable information).
- Anonymize data in exports and reports where possible.

## Conventions

- **Branches**: `main` (production), `feature/<ticket>` (development).
- **Commits**: Conventional Commits — `feat:`, `fix:`, `chore:`, `docs:`, `test:`.
- **PRs**: require at least 1 review before merging to `main`.
- **Language**: code, documentation, and comments in English.
- **Format**: Ruff with double quotes and line length 88. Do not modify without team consensus. Pre-commit hooks run Ruff automatically before every commit.
