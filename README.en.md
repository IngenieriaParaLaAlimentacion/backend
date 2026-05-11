# Backend

[![es](https://img.shields.io/badge/lang-es-green.svg)](README.md)
[![codecov](https://codecov.io/gh/IngenieriaParaLaAlimentacion/backend/graph/badge.svg?token=mR49XH6LdK)](https://app.codecov.io/gh/IngenieriaParaLaAlimentacion/backend)

REST API for the **Food Engineering** project, developed with FastAPI,
SQLAlchemy (async), and asyncpg on Python 3.11+.

------------------------------------------------------------------------

## Prerequisites

  Tool     Minimum Version
  -------- -----------------
  Python   3.11
  Poetry   2.0

> It is recommended to install Poetry with `pipx install poetry`.

------------------------------------------------------------------------

## Installation

``` bash
# 1. Clone the repository
git clone https://github.com/IngenieriaParaLaAlimentacion/backend.git

# 2. Install dependencies (including dev)
poetry install

# 3. Install pre-commit hooks
poetry run pre-commit install
```

------------------------------------------------------------------------

## Environment Variables

Create a `.env` file in the root of the `backend/` directory based on
`.env.example`.

> The project uses `pydantic-settings` to automatically load and
> validate environment variables.

------------------------------------------------------------------------

## Running the Application

``` bash
# Development server with hot-reload
poetry run uvicorn app.main:app --reload

# Or by activating the virtualenv first
poetry shell
uvicorn app.main:app --reload

# Using docker compose
docker compose up --build
```

The API will be available at `http://localhost:8000`.\
Interactive documentation (Swagger UI) is available at
`http://localhost:8000/docs`.

------------------------------------------------------------------------

## Tests

Integration tests use **Testcontainers** to spin up a real database in
an ephemeral environment.

``` bash
# Run all tests
poetry run pytest

# With coverage report
poetry run pytest --cov=app --cov-report=term-missing

# Run a specific file or test
poetry run pytest tests/test_example.py::test_function
```

------------------------------------------------------------------------

## Linting and Formatting

The project uses **Ruff** for linting (rules `E`, `F`, `I`) and
formatting (double quotes, line length 88).

``` bash
# Check for linting errors
poetry run ruff check .

# Automatically fix what can be fixed
poetry run ruff check . --fix

# Format the code
poetry run ruff format .
```

**pre-commit** hooks run these checks automatically before each commit.
To run them manually on all files:

``` bash
poetry run pre-commit run --all-files
```

------------------------------------------------------------------------

## License

Academic project --- **group-193**.
