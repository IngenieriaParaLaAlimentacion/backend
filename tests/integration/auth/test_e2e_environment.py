"""The environment file the backoffice E2E tests run the backend image with."""

from pathlib import Path
from uuid import uuid4

from dotenv import dotenv_values
from limits import parse as parse_limit

from app.config.settings import Settings, settings
from tests.integration.urls import LOGIN_URL

E2E_ENV_FILE = Path(__file__).parents[3] / "e2e" / ".env.e2e"

# Variables read by something other than the backend's settings.
_FOREIGN_PREFIXES = ("OTEL_",)

LOGINS_IN_A_MINUTE = 30


def _rate_limit_settings() -> list[str]:
    """Return the settings that hold a rate limit, written as ``<count>/<period>``."""
    names = []
    for name, field in Settings.model_fields.items():
        if not name.startswith("rate_limit_"):
            continue
        try:
            parse_limit(field.default)
        except ValueError:
            continue
        names.append(name)
    return names


def _backend_variables() -> dict[str, str]:
    """Return the file's variables that the backend reads, named as its settings."""
    return {
        name.lower(): value
        for name, value in dotenv_values(E2E_ENV_FILE).items()
        if not name.startswith(_FOREIGN_PREFIXES)
    }


def test_every_variable_is_a_backend_setting():
    """A misspelt name would be ignored, leaving the default in its place."""
    unknown = set(_backend_variables()) - set(Settings.model_fields)

    assert not unknown


def test_every_rate_limit_is_raised():
    """A limit the file leaves out keeps its default, which an E2E run can reach."""
    raised = set(_backend_variables())

    assert not set(_rate_limit_settings()) - raised


async def test_logins_in_a_minute_are_not_rate_limited(
    client, db_active_user, monkeypatch, fresh_limiter
):
    """The same user can log in 30 times in a minute from one address."""
    # The file is passed as arguments, which win over the variables the test run
    # already sets.
    e2e = Settings(_env_file=None, **_backend_variables())
    for name in (*_rate_limit_settings(), "rate_limit_redis_url"):
        monkeypatch.setattr(settings, name, getattr(e2e, name))

    statuses = [
        (
            await client.post(
                LOGIN_URL,
                json={
                    "email": db_active_user.email,
                    "password": "correct_password",
                    "device_id": str(uuid4()),
                },
                headers={"X-Real-IP": "1.1.1.1"},
            )
        ).status_code
        for _ in range(LOGINS_IN_A_MINUTE)
    ]

    assert statuses == [200] * LOGINS_IN_A_MINUTE
