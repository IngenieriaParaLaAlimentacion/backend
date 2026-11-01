# Ingeniería en Alimentación · Backend

[![es](https://img.shields.io/badge/lang-es-red.svg?logo=googletranslate&logoColor=white)](README.es.md)
[![codecov](https://codecov.io/gh/IngenieriaParaLaAlimentacion/backend/graph/badge.svg?token=IJ7UM97UZI)](https://codecov.io/gh/IngenieriaParaLaAlimentacion/backend)
[![Python](https://img.shields.io/badge/python-3.11+-3776AB.svg?logo=python&logoColor=white)](pyproject.toml)

REST API for the **Ingeniería para la Alimentación** project, built with FastAPI, SQLAlchemy (async) and asyncpg on Python 3.11+.

---

## Documentation

- [Commands](docs/commands.md): first-time setup, development, migrations, E2E reference data and data loading.
- [Architecture](docs/architecture.md).
- [Authentication and authorization](docs/auth.md).
- [Code conventions](docs/conventions.md).
- [API conventions](docs/api.md).
- [Error catalog](docs/errors.md).
- [Architecture decision records (ADRs)](docs/adr/).
- [Load tests](tests/load/README.md).
- [Stale-establishment push notifications: Firebase and Railway setup](docs/stale-establishment-push-railway-setup.md).
- [Contributing guide](CONTRIBUTING.md).
- [Development conventions for agents](CLAUDE.md).

---

## Prerequisites

| Tool | Minimum version | Notes |
|------|-----------------|-------|
| Python | 3.11 | |
| Poetry | 2.0 | Installing it with `pipx install poetry` is recommended |
| Docker | | Required for the integration tests (Testcontainers) and for `docker compose` |
| PostgreSQL | | Only for local development without Docker |
| Redis | | Used for rate limiting. Without Docker: `docker compose up redis` |
| Pango and HarfBuzz | | Native libraries needed by WeasyPrint. The app does not start without them |

To install Pango and HarfBuzz on macOS: `brew install pango`. On Debian or Ubuntu, the packages are listed in [docs/commands.md](docs/commands.md#prerequisites).

---

## Installation

```bash
# 1. Clone the repository
git clone https://github.com/IngenieriaParaLaAlimentacion/backend.git
cd backend

# 2. Install dependencies (including dev)
poetry install

# 3. Install pre-commit hooks
poetry run pre-commit install

# 4. Create the environment file
cp .env.example .env
```

---

## Environment variables

Edit the `.env` created from `.env.example` and change any values that differ from the defaults.

> The project uses `pydantic-settings` to load and validate environment variables automatically.

---

## Running

```bash
# With local PostgreSQL and DATABASE_HOST=localhost in .env:
poetry run alembic upgrade head
poetry run python seed_superadmin.py
poetry run python seed_food_catalog.py

# Development server with hot reload
poetry run uvicorn app.main:app --reload

# Or activate the virtualenv first
poetry shell
uvicorn app.main:app --reload

# Using docker compose
docker compose up --build
```

The API is available at `http://localhost:8080`.
The interactive documentation (Swagger UI) is at `http://localhost:8080/docs`.

---

## Tests

Integration tests use **Testcontainers** to start a real, ephemeral database, so Docker must be running.

```bash
# Run all tests
poetry run pytest

# Only unit tests or only integration tests
poetry run pytest tests/unit
poetry run pytest tests/integration

# With a coverage report
poetry run pytest --cov=app --cov-report=term-missing

# Run a specific file or test
poetry run pytest tests/unit/test_dates.py::test_completed_months_between
```

Load tests (k6) live in `tests/load/` and are described in [their README](tests/load/README.md). The reference data for the E2E tests is explained in [docs/commands.md](docs/commands.md#e2e-reference-data).

---

## Linting and formatting

The project uses **Ruff** for linting (rules `E`, `F`, `I`) and formatting (double quotes, line length 88).

```bash
# Check for lint errors
poetry run ruff check .

# Fix automatically what can be fixed
poetry run ruff check . --fix

# Format the code
poetry run ruff format .
```

**pre-commit** hooks run these checks automatically before every commit. To run them manually on all files:

```bash
poetry run pre-commit run --all-files
```

---

## Database migrations

`docker compose up --build` runs the `migrate` service first and then starts the backend. Restarting the backend does not migrate or seed again.

On Railway, set the backend service **Pre-Deploy Command** to `sh scripts/pre_deploy.sh` in both the test and production environments. It applies the migrations and runs the superadmin and food catalog seeds; if it fails, the new deployment does not start. The `Dockerfile` only starts Uvicorn.

To run the step manually:

```bash
poetry run alembic upgrade head && poetry run python seed_superadmin.py && poetry run python seed_food_catalog.py
```

To create or roll back migrations, see [docs/commands.md](docs/commands.md#database-and-migrations).

---

## Contributing

Read the [contributing guide](CONTRIBUTING.md) before opening a PR: branches, commits and review.

---

## License

Academic project — **grupo-193**.
