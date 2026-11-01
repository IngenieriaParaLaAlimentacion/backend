# Conventions

## Git workflow

Branches, pull requests and the CI checks are described in [CONTRIBUTING.md](../CONTRIBUTING.md). In short:

- `develop` is the integration branch and `main` the release branch. Never commit directly to either.
- Working branches use the `feat/`, `feature/`, `fix/`, `refactor/`, `docs/` or `chore/` prefix, and every PR targets `develop`.

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
| `ci` | CI workflows and pipeline configuration |

Examples:
```
feat: add height/weight registration endpoint
fix: resolve session leak on failed DB transaction
test: add unit tests for Settings defaults
docs: document the rate limit settings
```

### Pull requests

- Every PR targets `develop`. Only releases go from `develop` to `main`.
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
| `api/` | Parse HTTP input, call services, return responses | Contain business logic or DB queries |
| `services/<module>/` | Business logic and domain rules | Access the DB directly or know about HTTP |
| `repositories/<module>/` | DB queries only | Contain business logic |
| `models/<module>/` | ORM model definitions | Contain methods with business logic |
| `schemas/<module>/` | Request and response models | Contain business logic |
| `domain/` | Enums and plain domain types | Import from the layers above it |
| `core/` | Ports (`core/interfaces/`), FastAPI dependencies, security, rate limiting | Hold business rules |
| `config/` | Settings and observability configuration | Be used for anything other than configuration |
| `db/` | Engine, session factory and unit of work | Be imported by route handlers or services: they receive the unit of work through `core/dependencies.py` |

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

### Docstrings say what, comments say why

A docstring describes **what** the class or method does — the shape of what it returns and
the arguments that change it. It does not argue for the design: no comparisons against
rejected alternatives, no performance trade-offs, no history of why the code looks like
this. That kind of prose pushes the signature off the screen and goes stale the moment the
reasoning changes.

Rationale worth keeping goes in an inline `#` comment on the line it guards, where the
person about to change that line will actually read it:

```python
.join(User, User.id == source.model.responsible_id)
# Outer: a movement with no lines counts 0 instead of vanishing.
.outerjoin(source.item_model, source.item_fk == source.model.id)
```

`Raises:` sections stay — an exception a caller has to handle is part of the contract, not
rationale.
