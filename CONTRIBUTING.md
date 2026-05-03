# Contributing

## Development setup

1. Install dependencies:
```bash
poetry install
```

2. Install pre-commit hooks:
```bash
poetry run pre-commit install
```

From now on, every commit will automatically run the linter (`ruff`) via pre-commit.

## Branching

Use the following prefixes for branch names:

- `feature/` — new functionality
- `fix/` — bug fixes
- `chore/` — maintenance, dependencies, tooling
- `refactor/` — code restructuring without behavior changes
- `docs/` — documentation only
- `test/` — adding or fixing tests

Example: `feature/add-user-auth`, `fix/email-validation`, `chore/update-dependencies`

## Commits

This project follows [Conventional Commits](https://www.conventionalcommits.org/).

```
<type>(<scope>): <description>

feat(recetas): add search by ingredient endpoint
fix(auth): handle expired token correctly
chore(deps): bump ruff to 0.15.8
test(usuarios): add integration tests for registration
```

Common types: `feat`, `fix`, `chore`, `docs`, `test`, `refactor`, `ci`

## Pull Requests

- Every PR requires at least **one approval** before merging.
- Keep PRs small and focused — if a task is large, split it into incremental PRs.
- Delete the remote branch after merging.

## CI/CD

GitHub Actions runs on every push:

- Linter (`ruff`) via pre-commit
- Test suite
- Coverage upload to Codecov

### Codecov setup (maintainers only)

To enable Codecov on a new repo:

1. Go to [codecov.io](https://codecov.io) and find the repo
2. Copy the **Repository Upload Token** from Settings → General
3. Add it as a GitHub secret: Settings → Secrets and variables → Actions → New repository secret, named `CODECOV_TOKEN`

## Tests

Tests use **pytest** with **Testcontainers** for integration tests that need a real database instance. Make sure Docker is running before executing them.

```bash
# Run all tests
poetry run pytest

# With coverage report
poetry run pytest --cov=app --cov-report=term-missing
```

Aim to keep coverage above **80%**.