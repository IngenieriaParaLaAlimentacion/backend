"""Fixtures for the load-test data tests, taken from the integration suite.

These tests sit apart from the app's suites, so ``poetry run pytest`` never collects
them: run them with ``poetry run pytest tests/load/tests``.
"""

from tests.integration.conftest import *  # noqa: F403
