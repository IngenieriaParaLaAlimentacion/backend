# CLAUDE.md — tests

## Layout

`tests/unit/<domain>/` and `tests/integration/<domain>/` use the same domain folders, mirroring the app modules (`auth`, `admin`, `establishments`, `food`, `surveys`, ...).

| Type | What it covers | Needs Docker |
|---|---|---|
| `unit` | Services, schemas and pure logic, with a mocked UoW | No |
| `integration` | HTTP through the FastAPI app, repositories and DB constraints, on a real Postgres (Testcontainers) | Yes |

A module that grows too large is split into a folder by topic (e.g. `surveys/response_service/{submit,read,edit,export,dashboard}.py`).

## Where shared code goes

| Need | Put it in |
|---|---|
| Fixtures for the whole unit or integration suite | `tests/unit/conftest.py`, `tests/integration/conftest.py` |
| Fixtures for one domain folder | that folder's `conftest.py` |
| Plain functions and constants for one domain folder | that folder's `helpers.py` |
| Endpoint paths used by several modules | `tests/integration/urls.py` |
| Other helpers shared across integration modules | `tests/integration/helpers.py` |

Fixtures go in `conftest.py`, plain functions and constants in `helpers.py`. Look there before writing a new one, and never copy a fixture into a second 
folder: move it to the nearest common `conftest.py` (as was done with `foods`).

Most used shared fixtures:

- **Unit**: `make_uow`, `make_user`, `make_establishment`, `stub_establishment_lookup`; the helpers `drain`, `aiter_of` and `capturing_exporter` for
streamed exports.
- **Integration**: `client`, `admin_headers`, `analyst_headers`, `field_worker_headers`, `make_user_with_role`, `db_establishment`, `db_subject`, 
`make_field_worker_with_access`, `foods`. The database is cleaned between tests automatically.

## Principle: every test must earn its place

A test is worth keeping only if it fails when one of our rules breaks. Before adding one, check that no existing test would already fail for the same change. 
Prefer one more assertion or one more `parametrize` case in an existing test over a near-copy.

A test states the behavior we expect, taken from the requirement or acceptance criteria, and it guides the implementation, not the other way around. 
Never write a test by reading what the code does today and asserting exactly that. If a test fails, decide whether the code or the expectation is wrong; 
do not change an assertion just to make it pass. Assert observable outcomes (response, stored data, raised error); assert calls to collaborators only when
they are the contract, such as "nothing is committed on failure".

Avoid:

- A test that mirrors the implementation: the same branches, the same internal calls, the exact values the code happens to produce.
- A second test asserting what another already asserts (a status check repeated next to a test that reads the body, an `isinstance` next to the field checks).
- Tests that only echo a mock: asserting the value the mock was just given.
- Tests of defaults, message wording or framework validation.

## Conventions

- Async tests need no marker: `asyncio_mode = "auto"`.
- Import `AsyncSessionLocal` inside the fixture or test, not at module level. The `app` fixture repoints it to the test container, and a module-level 
  import would bind the real engine.
- One behavior per test. Name it after the behavior, and after the status for HTTP tests (`test_unknown_id_returns_404`).
- Cases that differ in one value use `@pytest.mark.parametrize`, not copies of the test.
- Test our rules, not what the framework already guarantees (Pydantic defaults, FastAPI path or query validation, message wording).
- Do not repeat at integration level what a unit test already pins, unless it is the HTTP contract or the wiring.
- Docstrings say what the test checks. The reason behind a non-obvious assertion goes in an inline `#` comment, as in the rest of the codebase (`docs/conventions.md`).

## Running

```bash
poetry run pytest tests/unit/    # no Docker needed
poetry run pytest                # everything; Docker must be running
poetry run pytest --cov=app      # with coverage
```

More commands in `docs/commands.md`.
