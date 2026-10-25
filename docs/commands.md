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

### Published image

Every push to `develop` and `main` publishes the image to GitHub Container Registry, once the lint, the tests and the security scan pass and the image has started and answered `/ready` against an empty PostgreSQL. A push to any other branch, which is what a pull request is built from, publishes nothing.

| | |
|---|---|
| Image | `ghcr.io/ingenieriaparalaalimentacion/backend` |
| `develop`, `main` | The latest commit of that branch |
| `sha-<commit>` | That exact commit (the full 40-character hash); never changes |

The image is private. From a workflow of another repository of the organization, log in with its own token; the package grants that repository read access:

```yaml
permissions:
  packages: read
steps:
  - uses: docker/login-action@v3
    with:
      registry: ghcr.io
      username: ${{ github.actor }}
      password: ${{ secrets.GITHUB_TOKEN }}
```

From a machine, log in with a personal access token that has the `read:packages` scope.

#### Run it with its dependencies

`e2e/compose.yml` starts the image next to PostgreSQL, applies the migrations and seeds, and waits until `/ready` answers:

```bash
# Start (BACKEND_IMAGE picks another tag; the default is develop)
docker compose -f e2e/compose.yml up --wait

# Stop and drop the database
docker compose -f e2e/compose.yml down -v
```

The API listens on `http://localhost:8080`. The configuration is `e2e/.env.e2e`, which holds throwaway test values only: no real secret goes in it. With it the backend needs no file storage, Gemini, SMTP or Redis, and the rate limits are high enough for the same user to log in repeatedly. The seeded superadmin is the `SEED_ADMIN_EMAIL` and `SEED_ADMIN_PASSWORD` of that file.

### Integration tests without Docker

`TEST_POSTGRES_URL` may point to a **disposable test-only** PostgreSQL instance
(e.g. `postgresql+psycopg2://test@127.0.0.1:55432/test`). The suite runs migrations
and truncates every application table. Never use an application database.
Redis-backed auth rate-limit tests still require their Redis Testcontainer.
