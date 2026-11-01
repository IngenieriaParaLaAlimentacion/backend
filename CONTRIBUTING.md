# Contributing

## Development setup

Follow the [installation steps in the README](README.md#installation). Full setup, migration and E2E data commands are in [`docs/commands.md`](docs/commands.md).

Installing the pre-commit hooks (`poetry run pre-commit install`) makes every commit run the linter and formatter (`ruff`) automatically.

## Branching

We use two long-lived branches:

- `develop`: integration branch. Every working branch starts from `develop` and goes back into `develop` through a PR.
- `main`: release branch. It only receives PRs from `develop`. Never merge working branches into it or commit directly to `main`.

CI ([`pr-branch-policy.yaml`](.github/workflows/pr-branch-policy.yaml)) enforces this on every PR:

- PRs into `develop` must come from `feat/*`, `feature/*`, `fix/*`, `refactor/*`, `docs/*` or `chore/*`.
- PRs into `main` are only accepted from `develop`.

Examples: `feat/add-user-auth`, `fix/email-validation`, `chore/update-dependencies`, `docs/improve-docs`.

## Commits

This project follows [Conventional Commits](https://www.conventionalcommits.org/). Scope is optional.

```
<type>(<scope>): <description>

feat(recetas): add search by ingredient endpoint
fix(auth): handle expired token correctly
chore(deps): bump ruff to 0.15.8
test(usuarios): add integration tests for registration
```

Common types: `feat`, `fix`, `chore`, `docs`, `test`, `refactor`, `ci`.

## Pull Requests

- Target `develop`. Only releases go from `develop` to `main`.
- Every PR requires at least **one approval** before merging.
- Keep PRs small and focused. If a task is large, split it into incremental PRs.
- Delete the remote branch after merging.

## CI/CD

GitHub Actions runs [`ci.yml`](.github/workflows/ci.yml) on every push:

- Lint and format check through pre-commit (`ruff`).
- Unit tests (`tests/unit`) and integration tests (`tests/integration`), each uploading coverage to Codecov.
- Semgrep SAST scan.
- Docker image build, checked by starting the backend with the E2E compose (`e2e/compose.yml`). The image is published to GHCR only from `develop` and `main`.

Other workflows:

- [`pr-branch-policy.yaml`](.github/workflows/pr-branch-policy.yaml) validates the source branch of every PR into `develop` or `main`.
- [`load-tests.yml`](.github/workflows/load-tests.yml) runs the k6 load tests on demand. See [`tests/load/README.md`](tests/load/README.md).
- [`claude.yml`](.github/workflows/claude.yml) runs Claude Code on issue and pull request comments.

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

# Only unit tests or only integration tests
poetry run pytest tests/unit
poetry run pytest tests/integration

# With coverage report
poetry run pytest --cov=app --cov-report=term-missing
```

Codecov expects at least **70%** coverage for the project and for every patch ([`codecov.yml`](codecov.yml)).
