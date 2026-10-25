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

## E2E reference data

`seed_reference_e2e.py` loads a fictitious dataset, so E2E tests and the user manual's screenshots start from the same state. It is **never** run by the service startup or the deploy: run it by hand against a disposable database, after the migrations and the seeds of the superadmin and the food catalog.

```bash
# Locally
ENVIRONMENT=test poetry run python seed_reference_e2e.py

# With the development compose
docker compose run --rm -e ENVIRONMENT=test backend python seed_reference_e2e.py
```

It only runs when `ENVIRONMENT` is `test` or `e2e`, and says so otherwise. A deploy that does not set it falls back to `development`, so it cannot load this data by mistake. Running it again adds nothing that is already there. The API has almost no way to delete data, so to start over, use a new database.

What it loads:

| | |
|---|---|
| Establishments | 6 community kitchens, named after public squares in Buenos Aires, Córdoba, Mendoza, Salta, Resistencia and Bariloche |
| Subjects | 15 people aged 25 or less, each with 3 measurements over the last year; some trigger alerts |
| Stock | Deliveries and outflows at every establishment, registered through the services |
| Survey | An active FIES survey, anonymous, with 10 responses |
| Requests | 2 pending requests to create an establishment, and 1 user waiting for approval |

Every user below has the same password, `Referencia-123!`. All the data is made up.

| Role | Email | Works in |
|---|---|---|
| Admin | `admin.referencia@tpp.com` | all |
| Analyst | `analista.referencia@tpp.com` | all |
| Field worker | `relevador1.referencia@tpp.com` | Buenos Aires, Córdoba |
| Field worker | `relevador2.referencia@tpp.com` | Mendoza, Salta |
| Field worker | `relevador3.referencia@tpp.com` | Resistencia, Bariloche |
| Field worker, pending | `pendiente.referencia@tpp.com` | awaits approval; cannot log in |

The superadmin is the one the seed already creates.

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

The image and `e2e/compose.yml` are versioned together. From another repository, check this one out at the commit the image was built from and set `BACKEND_IMAGE` to the matching `sha-<commit>` tag, so that both match. The default, `develop`, moves with every merge: it is fine on a machine, but two runs of a CI can then use different images, and the compose they downloaded may not fit the one they run.

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
