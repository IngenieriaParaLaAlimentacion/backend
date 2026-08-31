"""Guards docs/errors.md and docs/errors.json against drift.

Regenerate with: poetry run python docs/generate_error_catalog.py
"""

import importlib.util
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

_spec = importlib.util.spec_from_file_location(
    "generate_error_catalog", PROJECT_ROOT / "docs" / "generate_error_catalog.py"
)
generate_error_catalog = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(generate_error_catalog)


def test_committed_catalog_matches_the_registry():
    markdown, catalog = generate_error_catalog.build_catalog()

    assert generate_error_catalog.MARKDOWN_PATH.read_text(encoding="utf-8") == markdown
    assert (
        json.loads(generate_error_catalog.JSON_PATH.read_text(encoding="utf-8"))
        == catalog
    )
