# Commands

## Prerequisites

- Python 3.11+
- [Poetry 2.0+](https://python-poetry.org/docs/#installation)
- Docker (required for running tests)
- A running PostgreSQL instance (for local dev without Docker)
- A running Redis instance for rate limiting (for local dev without Docker; `docker compose up redis`)

---

## First-time setup

```bash
# 1. Install dependencies
poetry install

# 2. Install pre-commit hooks
poetry run pre-commit install

# 3. Create your local .env from the example
cp .env.example .env
```

Edit `.env` and set any values that differ from the defaults. To copy all neded env vars easily:
```
cp .env.example .env
```

---

## Development

```bash
# Run the dev server (hot reload)
poetry run uvicorn app.main:app --reload
# Listening on http://0.0.0.0:8080
```

---

## Database and migrations

```bash
# Apply all pending migrations
poetry run alembic upgrade head

# Roll back one migration
poetry run alembic downgrade -1

# Generate a new migration from model changes
poetry run alembic revision --autogenerate -m "short description"

# Show current migration state
poetry run alembic current
```

> Never modify the DB schema manually. All changes go through Alembic migrations.

---

## Testing

Tests use [Testcontainers](https://testcontainers.com/) to spin up a real PostgreSQL instance, and a Redis for the rate-limit tests. **Docker must be running.**

```bash
# Run all tests
poetry run pytest

# Run only unit tests
poetry run pytest tests/unit/

# Run with coverage report
poetry run pytest --cov=app

# Run a specific file or test
poetry run pytest tests/unit/core/test_config.py
poetry run pytest tests/unit/core/test_config.py::test_build_database_url_from_parts
```

---

## Code quality

Pre-commit hooks run these automatically before every commit. To run manually:

```bash
# Lint and auto-fix
poetry run ruff check . --fix

# Format
poetry run ruff format .

# Both in one line
poetry run ruff check . --fix && poetry run ruff format .
```

---

## Docker

The Dockerfile uses a multi-stage build. On startup it runs migrations automatically before launching the server.

```bash
# Build the image
docker build -t backend .

# Run the container
docker run --env-file .env -p 8080:8080 backend
```

The container entrypoint runs:
```bash
alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8080
```

All configuration is passed via environment variables (see `.env.example`).


### Integration tests without Docker

`TEST_POSTGRES_URL` may point to a **disposable test-only** PostgreSQL instance
(e.g. `postgresql+psycopg2://test@127.0.0.1:55432/test`). The suite runs migrations
and truncates every application table. Never use an application database.
Redis-backed auth rate-limit tests still require their Redis Testcontainer.
