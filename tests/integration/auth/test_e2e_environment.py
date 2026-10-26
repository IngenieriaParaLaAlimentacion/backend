"""The environment file the backoffice E2E tests run the backend image with."""

from pathlib import Path
from uuid import uuid4

from dotenv import dotenv_values

from app.config.settings import Settings, settings
from tests.integration.urls import LOGIN_URL

E2E_ENV_FILE = Path(__file__).parents[3] / "e2e" / ".env.e2e"

# Variables read by something other than the backend's settings.
_FOREIGN_PREFIXES = ("OTEL_",)

_RATE_LIMITS = (
    "rate_limit_login_email",
    "rate_limit_login_ip",
    "rate_limit_token_ip",
    "rate_limit_register_ip",
    "rate_limit_mail_sending_email",
    "rate_limit_mail_sending_ip",
)

LOGINS_IN_A_MINUTE = 30


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


async def test_logins_in_a_minute_are_not_rate_limited(
    client, db_active_user, monkeypatch, fresh_limiter
):
    """The same user can log in 30 times in a minute from one address."""
    # The file is passed as arguments, which win over the variables the test run
    # already sets.
    e2e = Settings(_env_file=None, **_backend_variables())
    for name in (*_RATE_LIMITS, "rate_limit_redis_url"):
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
