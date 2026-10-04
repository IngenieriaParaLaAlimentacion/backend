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

# The suite hits the public auth endpoints from a single client address, far more
# often than any real caller would, so every limit starts out effectively off and
# counters live in memory rather than Redis. Rate-limit tests lower the specific
# limit they exercise. Read when app.core.rate_limit is imported, so it must be
# set before that.
os.environ.setdefault("RATE_LIMIT_REDIS_URL", "memory://")
for _limit in (
    "LOGIN_EMAIL",
    "LOGIN_IP",
    "MAIL_SENDING_EMAIL",
    "MAIL_SENDING_IP",
    "TOKEN_IP",
    "REGISTER_IP",
):
    os.environ.setdefault(f"RATE_LIMIT_{_limit}", "1000000/minute")
