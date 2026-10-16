"""Guards docs/errors.md and docs/errors.json against drift.

Regenerate with: poetry run python docs/generate_error_catalog.py
"""

import importlib.util
import json

import pytest


@pytest.fixture(scope="module")
def generate_error_catalog(pytestconfig):
    """Load the error catalog generator script from docs/."""
    # docs/ is not a package, so the script is loaded from its path. The path is
    # anchored on pytest's rootdir so the test can live at any depth.
    script = pytestconfig.rootpath / "docs" / "generate_error_catalog.py"
    spec = importlib.util.spec_from_file_location("generate_error_catalog", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_committed_catalog_matches_the_registry(generate_error_catalog):
    markdown, catalog = generate_error_catalog.build_catalog()

    assert generate_error_catalog.MARKDOWN_PATH.read_text(encoding="utf-8") == markdown
    assert (
        json.loads(generate_error_catalog.JSON_PATH.read_text(encoding="utf-8"))
        == catalog
    )
