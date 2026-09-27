"""
Root test configuration.

Fixtures shared across all test types live here.
Type-specific fixtures are in their own conftest:
  - tests/unit/conftest.py        — mock factories for unit tests
  - tests/integration/conftest.py — database, app, and HTTP client setup
"""

import os

# Tests verify that the telemetry wiring is set up, not that data is exported:
# test runs never ship traces, metrics or logs to a backend. The standard
# OTEL_SDK_DISABLED switch turns every signal into a no-op while the app is still
# built with its instrumentation. Read when app.main is imported, so it must be
# set before that; setdefault lets a developer override it.
os.environ.setdefault("OTEL_SDK_DISABLED", "true")
