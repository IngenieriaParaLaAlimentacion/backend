# Conventions

## Git workflow

### Branches

| Branch | Purpose |
|---|---|
| `main` | Production. Never commit directly. |
| `feature/<ticket>` | All development work. |

Examples: `feature/AUTH-12`, `feature/nutrir-meal-endpoint`.

### Commit messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>: <short description in imperative mood>
```

| Type | When to use |
|---|---|
| `feat` | New feature or endpoint |
| `fix` | Bug fix |
| `chore` | Tooling, dependencies, config |
| `docs` | Documentation only |
| `test` | Adding or updating tests |
| `refactor` | Code change that neither fixes a bug nor adds a feature |

Examples:
```
feat: add height/weight registration endpoint
fix: resolve session leak on failed DB transaction
test: add unit tests for Settings defaults
docs: document auth middleware behavior
```

### Pull requests

- Every PR targets `main`.
- At least 1 review required before merging.
- PR description must explain what changed and why.

---

## Code style

### Language

All code, comments, and documentation must be written in **English**.

### Formatting

Enforced by [Ruff](https://docs.astral.sh/ruff/) with the following configuration (see `pyproject.toml`):

- Line length: **88 characters**
- Quotes: **double**
- Rules: `E` (pycodestyle), `F` (pyflakes), `I` (isort)

Run manually:
```bash
poetry run ruff check . --fix
poetry run ruff format .
```

### Pre-commit hooks

Ruff runs automatically before every commit. To install:
```bash
pre-commit install
```

The hooks run `ruff --fix` (lint + auto-fix) and `ruff format` on staged files. A commit is blocked if any issue cannot be auto-fixed.

---

## Layer separation

Each layer has a single responsibility. Do not cross boundaries:

| Layer | Responsibility | Must not |
|---|---|---|
| `api/<module>/` | Parse HTTP input, call services, return responses | Contain business logic or DB queries |
| `services/<module>/` | Business logic and domain rules | Access the DB directly or know about HTTP |
| `repositories/<module>/` | DB queries only | Contain business logic |
| `models/<module>/` | ORM model definitions | Contain methods with business logic |
| `db/` | Engine and session factory | Be imported outside repositories and Alembic |
| `core/` | App settings | Be used for anything other than configuration |

---

## Naming conventions

Follow standard Python conventions ([PEP 8](https://peps.python.org/pep-0008/)):

| Element | Convention | Example |
|---|---|---|
| Functions and methods | `snake_case` | `get_measurement_by_id` |
| Variables | `snake_case` | `session_factory` |
| Classes | `PascalCase` | `MeasurementRepository` |
| Constants | `UPPER_SNAKE_CASE` | `MAX_RETRY_COUNT` |
| Modules and files | `snake_case` | `database.py`, `user_repository.py` |

---

## Documentation

All public classes and methods must have a docstring. One line is enough for simple cases.

```python
class MeasurementRepository:
    """Handles all DB access for the talla_y_peso module."""

    async def get_by_subject(self, subject_id: int) -> list[Measurement]:
        """Return all measurements for the given subject."""
        ...
```

Private methods (prefixed with `_`) do not require a docstring unless the behavior is non-obvious.
