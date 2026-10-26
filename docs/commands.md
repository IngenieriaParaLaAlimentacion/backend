# Commands

## Prerequisites

- Python 3.11+
- [Poetry 2.0+](https://python-poetry.org/docs/#installation)
- Docker (required for Testcontainers-based integration tests)
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

### AI configuration

AI credentials are backend-only. Configure OPENROUTER_API_KEY, ordered JSON
arrays OPENROUTER_RECEIPT_MODELS / OPENROUTER_RECIPE_MODELS, and audited
OPENROUTER_ALLOWED_PROVIDERS. Defaults leave inference unavailable while
non-AI flows still run. Model IDs are read from these environment arrays without
a startup naming restriction. Runtime eligibility and zero-price request caps
permit only qualified, current :free variants; there is no paid fallback.
The gateway's account quota is shared across models.

Before enabling a model, verify its live model/endpoint prices, image support
where needed, strict schema behavior, Spanish task quality, latency and data
policy using synthetic inputs. Never qualify by catalogue metadata alone.
Recheck after model/provider changes or expiry. Do not send personal receipt
images to endpoints whose terms prohibit them. If no acceptable endpoint exists,
keep receipt AI unavailable and preserve manual intake.

Deploy with these settings present in each target environment. The application
does not consume legacy GEMINI_* settings. Roll back the application artifact
and its matching environment snapshot together if needed; no schema downgrade
is introduced by this feature. Config changes require restarting the service.

---

## Development

```bash
# With local PostgreSQL, set DATABASE_HOST=localhost in .env, then:
poetry run alembic upgrade head
poetry run python seed_superadmin.py
poetry run python seed_food_catalog.py

# Run the dev server (hot reload)
poetry run uvicorn app.main:app --reload
# Listening on http://0.0.0.0:8080
```

---

## Database and migrations

```bash
# Apply all pending migrations
poetry run alembic upgrade head

# Roll back to a specific revision (example: one parent of the current merge head)
poetry run alembic downgrade b7d170a4e901

# Generate a new migration from model changes
poetry run alembic revision --autogenerate -m "short description"

# Show current migration state
poetry run alembic current
```

> Never modify the DB schema manually. All changes go through Alembic migrations.

---

## Testing

Integration tests use [Testcontainers](https://testcontainers.com/) to spin up a real PostgreSQL instance, and a Redis for the rate-limit tests. Docker must be running for those tests unless `TEST_POSTGRES_URL` points to a disposable PostgreSQL instance; Redis-backed tests still need Docker.

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

The Dockerfile uses a multi-stage build. Its startup command runs only Uvicorn. With Compose, the one-shot `migrate` service runs migrations and both seeds before the backend starts.

```bash
# Build the image
docker build -t backend .

# Run the container after applying migrations and seeds to its database
docker run --env-file .env -p 8080:8080 backend
```

For local Compose, run:
```bash
docker compose up --build
```

Before deploying this change in Railway, set the backend service's **Pre-Deploy Command** to `sh scripts/pre_deploy.sh` in both test and production. The script logs each step, applies `alembic upgrade head`, and runs `seed_superadmin.py` and `seed_food_catalog.py`; a failure stops the new deployment. This setting must be checked in both Railway environments because this checkout has no linked Railway project. If a seed fails after Alembic succeeds, the earlier database migration is not automatically undone.

All configuration is passed via environment variables (see `.env.example`). If `DATABASE_URL` is set, it takes precedence over the individual database fields, including Compose's `DATABASE_HOST=postgres` override.

### Migration rollback limits

CI checks that the current head can run `upgrade head`, downgrade to its parent revision (or both parents for a merge head), and `upgrade head` on a fresh PostgreSQL Testcontainer. This checks command success and revision movement, but it does not prove that every historical migration restores data or schema exactly. Known exceptions include:

- `3c300b242b41`, `9c55bed7c3d6`, and `9dfcb864e5a1`: PostgreSQL enum additions remain after downgrade.
- `e515758f7b0a`: the email-verification backfill has no reverse data operation.
- `c7d4e9a2b8f1`: upgrade deletes survey responses, which downgrade cannot restore.
- `3f8d2a1b9c4e`: downgrade drops geocoding columns and their data.
- `c9a4b7e2f168`: an orphan stub has no schema operations, and historical databases may differ from fresh ones.

Back up a populated database and review each migration before relying on downgrade as a rollback procedure.

### Integration tests without Docker

`TEST_POSTGRES_URL` may point to a **disposable test-only** PostgreSQL instance
(e.g. `postgresql+psycopg2://test@127.0.0.1:55432/test`). The suite runs migrations
and truncates every application table. Never use an application database.
Redis-backed auth rate-limit tests still require their Redis Testcontainer.
