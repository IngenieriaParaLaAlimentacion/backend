"""Generate the public error catalog from the exception registry.

Run: env -u VIRTUAL_ENV poetry run python docs/generate_error_catalog.py
Drift is guarded by tests/unit/test_error_catalog_is_current.py.
"""

import inspect
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MARKDOWN_PATH = PROJECT_ROOT / "docs" / "errors.md"
JSON_PATH = PROJECT_ROOT / "docs" / "errors.json"

_HEADER = """<!-- GENERATED FILE - do not edit by hand.
     Run: poetry run python docs/generate_error_catalog.py -->

# Error catalog

Every error response is `application/problem+json`. The `type` member below is the
stable, machine-readable identifier: **branch on it**. `title` and `detail` are
human-readable prose and may be reworded at any time.

The catalog is additive-only: new values may be added, existing values are not
renamed or removed without notice.

Some errors also carry a `reason` member -- a machine-readable sub-code for a
variant within one `type` (e.g. why a survey is locked) -- and/or RFC 7807
extension members such as `user_id` or `relation_status`.

Five `type` values are produced by the framework rather than by a domain
exception and so are not in the registry: `/errors/validation-failed` (422),
`/errors/http-error` (400, a request body that is not valid UTF-8),
`/errors/not-found` (404, unrouted path), `/errors/method-not-allowed` (405) and
`/errors/internal-error` (500).

| `type` | Status | Exception | Description |
|---|---|---|---|
"""


def _description(cls: type) -> str:
    """First line of the class docstring, collapsed onto one line."""
    doc = inspect.getdoc(cls) or ""
    first = doc.split("\n\n")[0]
    return " ".join(first.split())


def build_catalog() -> tuple[str, dict]:
    """Return the (markdown, json-serializable) catalog for the registry."""
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

    from app.exceptions.domain_exceptions import ERROR_REGISTRY

    entries = [
        {
            "type": f"/errors/{slug}",
            "status": cls.status,
            "exception": cls.__name__,
            "description": _description(cls),
        }
        for slug, cls in sorted(ERROR_REGISTRY.items())
    ]

    rows = "".join(
        f"| `{entry['type']}` | {entry['status']} | `{entry['exception']}` "
        f"| {entry['description']} |\n"
        for entry in entries
    )
    return _HEADER + rows, {"errors": entries}


def main() -> None:
    markdown, catalog = build_catalog()
    MARKDOWN_PATH.write_text(markdown, encoding="utf-8")
    JSON_PATH.write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"OK: {MARKDOWN_PATH}")
    print(f"OK: {JSON_PATH}")


if __name__ == "__main__":
    main()
